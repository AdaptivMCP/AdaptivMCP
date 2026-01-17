"""Render API client helpers.

This module provides a thin, well-instrumented wrapper around Render's public
API for use by MCP tools.

Design goals:
- No synthetic payloads in production.
- Tool outputs contain the real Render responses (no truncation).
- Provider logs are human-readable and correlate with inbound tool calls.
"""

from __future__ import annotations

import importlib.util
import os
import time
from typing import Any, Dict, Optional

from github_mcp.config import (
    BASE_LOGGER,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    LOG_INLINE_CONTEXT,
    LOG_RENDER_HTTP,
    LOG_RENDER_HTTP_BODIES,
    RENDER_API_BASE,
    RENDER_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS,
    RENDER_RATE_LIMIT_RETRY_MAX_ATTEMPTS,
    RENDER_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS,
    RENDER_TOKEN_ENV_VARS,
    format_log_context,
    summarize_request_context,
)
from github_mcp.exceptions import RenderAPIError, RenderAuthError
from github_mcp.http_clients import _get_concurrency_semaphore
from github_mcp.mcp_server.context import get_request_context

if importlib.util.find_spec("httpx") is not None:  # pragma: no cover
    import httpx
else:  # pragma: no cover
    # The project vendors a fallback httpx shim in github_mcp.http_clients, but
    # Render API tools require httpx at runtime.
    httpx = None  # type: ignore[assignment]


_http_client_render: Optional["httpx.AsyncClient"] = None
_http_client_render_loop: Optional["asyncio.AbstractEventLoop"] = None
_http_client_render_token: Optional[str] = None
_http_client_render_base: Optional[str] = None
_render_api_version_prefix: str = "/v1"


def _normalize_render_api_base(raw_base: str) -> tuple[str, str]:
    """Normalize Render API base URL and versioning.

    Operators may set RENDER_API_BASE as either:
    - https://api.render.com
    - https://api.render.com/v1

    If the base ends with /v1 and callers also pass /v1-prefixed paths, requests
    become /v1/v1/... and Render returns 404.

    This helper strips a trailing /v1 from the base URL and returns the version
    prefix that may be applied to request paths.
    """

    base = (raw_base or "").strip()
    if not base:
        return "https://api.render.com", "/v1"

    trimmed = base.rstrip("/")
    if trimmed.endswith("/v1"):
        stripped = trimmed[: -len("/v1")] or "https://api.render.com"
        return stripped, "/v1"

    return trimmed, "/v1"


def _apply_render_version_prefix(path: str) -> str:
    """Ensure exactly one version prefix is applied to the request path."""

    p = (path or "").strip()
    if not p.startswith("/"):
        p = "/" + p

    prefix = (_render_api_version_prefix or "").strip()
    if not prefix:
        return p
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    prefix = prefix.rstrip("/")

    if p == prefix or p.startswith(prefix + "/"):
        return p
    return prefix + p


def _get_render_token() -> str:
    token = None
    token_source = None
    for env_var in RENDER_TOKEN_ENV_VARS:
        candidate = os.environ.get(env_var)
        if candidate is not None:
            token = candidate
            token_source = env_var
            break

    if token is None:
        raise RenderAuthError(
            "Render authentication failed: token is not configured (set RENDER_API_KEY or RENDER_API_TOKEN)"
        )

    token = token.strip()
    if not token:
        raise RenderAuthError(f"Render authentication failed: {token_source or 'token'} is empty")

    return token


def _get_optional_render_token() -> Optional[str]:
    for env_var in RENDER_TOKEN_ENV_VARS:
        candidate = os.environ.get(env_var)
        if candidate is not None:
            token = candidate.strip()
            return token or None
    return None


def _refresh_async_client(
    client: Optional["httpx.AsyncClient"],
    *,
    client_loop: Optional[asyncio.AbstractEventLoop],
    rebuild,
    force_refresh: bool = False,
):
    from .async_utils import refresh_async_client

    def _log_debug(msg: str) -> None:
        BASE_LOGGER.debug(msg)

    def _log_debug_exc(msg: str) -> None:
        BASE_LOGGER.debug(msg, exc_info=True)

    refreshed, loop = refresh_async_client(
        client,
        client_loop=client_loop,
        rebuild=rebuild,
        force_refresh=force_refresh,
        log_debug=_log_debug,
        log_debug_exc=_log_debug_exc,
    )
    return refreshed, loop


def _render_client_instance() -> "httpx.AsyncClient":
    """Singleton async client for Render API requests."""

    global \
        _http_client_render, \
        _http_client_render_loop, \
        _http_client_render_token, \
        _http_client_render_base, \
        _render_api_version_prefix

    current_token = _get_optional_render_token()
    token_changed = current_token != _http_client_render_token

    normalized_base, version_prefix = _normalize_render_api_base(RENDER_API_BASE)
    base_changed = normalized_base != _http_client_render_base

    def _build_client() -> "httpx.AsyncClient":
        token = current_token or ""
        # Keep base/path composition stable regardless of whether RENDER_API_BASE includes /v1.
        nonlocal normalized_base, version_prefix
        _render_api_version_prefix = version_prefix
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        limits = httpx.Limits(
            max_connections=HTTPX_MAX_CONNECTIONS,
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
        )
        return httpx.AsyncClient(
            base_url=normalized_base,
            timeout=HTTPX_TIMEOUT,
            limits=limits,
            headers=headers,
        )

    _http_client_render, _http_client_render_loop = _refresh_async_client(
        _http_client_render,
        client_loop=_http_client_render_loop,
        rebuild=_build_client,
        force_refresh=token_changed or base_changed,
    )
    _http_client_render_token = current_token
    _http_client_render_base = normalized_base
    return _http_client_render


def _parse_rate_limit_delay_seconds(resp: "httpx.Response") -> Optional[float]:
    from .http_utils import parse_rate_limit_delay_seconds

    return parse_rate_limit_delay_seconds(
        resp,
        reset_header_names=("Ratelimit-Reset", "X-RateLimit-Reset"),
        allow_epoch_millis=True,
        allow_duration_seconds=True,
    )


def _extract_response_body(resp: "httpx.Response") -> Any | None:
    from .http_utils import extract_response_json

    return extract_response_json(resp)


def _build_response_payload(resp: "httpx.Response", *, body: Any | None = None) -> Dict[str, Any]:
    # Backward-compatible wrapper for shared response payload builder.
    from github_mcp.http_utils import build_response_payload

    return build_response_payload(resp, body=body)


async def _send_request(
    client: "httpx.AsyncClient",
    *,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]],
    json_body: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]],
) -> "httpx.Response":
    async with _get_concurrency_semaphore():
        return await client.request(
            method,
            path,
            params=params,
            json=json_body,
            headers=headers,
        )


async def render_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    expect_json: bool = True,
    require_auth: bool = True,
) -> Dict[str, Any]:
    """Async Render request wrapper with structured errors and logging."""

    if require_auth:
        _get_render_token()

    attempt = 0
    max_attempts = max(0, RENDER_RATE_LIMIT_RETRY_MAX_ATTEMPTS)

    while True:
        started = time.perf_counter()
        client = _render_client_instance()
        effective_path = _apply_render_version_prefix(path)
        try:
            resp = await _send_request(
                client,
                method=method,
                path=effective_path,
                params=params,
                json_body=json_body,
                headers=headers,
            )
        except Exception as exc:
            raise RenderAPIError(f"Render request failed: {exc}") from exc

        body: Any | None = _extract_response_body(resp)
        error_flag = getattr(resp, "is_error", None)
        if error_flag is None:
            error_flag = getattr(resp, "status_code", 0) >= 400

        if LOG_RENDER_HTTP:
            req = get_request_context()
            duration_ms = (time.perf_counter() - started) * 1000
            inline_ctx = ""
            if LOG_INLINE_CONTEXT:
                try:
                    inline_ctx = format_log_context(req)
                except Exception:
                    inline_ctx = ""
            payload: Dict[str, Any] = {
                "event": "render_http",
                "request": summarize_request_context(req) if isinstance(req, dict) else {},
                "log_context": inline_ctx or None,
                "method": str(method).upper(),
                "path": effective_path,
                "status_code": getattr(resp, "status_code", None),
                "duration_ms": duration_ms,
            }
            if params is not None:
                payload["params"] = params
            if json_body is not None:
                payload["json_body"] = json_body
            if headers is not None:
                safe_headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
                payload["headers"] = safe_headers
            if LOG_RENDER_HTTP_BODIES:
                payload["response_headers"] = dict(getattr(resp, "headers", {}) or {})
                payload["response_body"] = body if body is not None else getattr(resp, "text", "")

            msg = (
                f"render_http method={str(method).upper()} path={effective_path} "
                f"status={getattr(resp, 'status_code', None)} duration_ms={duration_ms:.2f}"
            )
            if inline_ctx:
                msg = msg + " " + inline_ctx
            BASE_LOGGER.info(msg, extra=payload)

        status_code = getattr(resp, "status_code", 0)
        if status_code in (401, 403):
            message = None
            if isinstance(body, dict):
                message = body.get("message") or body.get("error")
            raise RenderAuthError(
                f"Render authentication failed: {status_code} {message or 'Authentication failed'}"
            )

        if status_code == 429:
            header_delay = _parse_rate_limit_delay_seconds(resp)
            retry_delay = header_delay
            if retry_delay is None:
                retry_delay = RENDER_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS * (2**attempt)

            if attempt < max_attempts and retry_delay <= RENDER_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS:
                # Apply jitter to reduce synchronized retry storms.
                from .retry_utils import jitter_sleep_seconds

                await asyncio.sleep(
                    jitter_sleep_seconds(
                        retry_delay,
                        respect_min=header_delay is not None,
                        cap_seconds=1.0,
                    )
                )
                attempt += 1
                continue

            raise RenderAPIError(
                "Render rate limit exceeded",
                status_code=status_code,
                response_payload=_build_response_payload(resp, body=body),
            )

        if error_flag:
            payload = _build_response_payload(resp, body=body)
            raise RenderAPIError(
                f"Render API error {status_code}: {getattr(resp, 'text', '')}",
                status_code=status_code,
                response_payload=payload,
            )

        result = _build_response_payload(resp, body=body)
        if expect_json:
            result["json"] = body if body is not None else {}
        return result


__all__ = [
    "_get_optional_render_token",
    "_get_render_token",
    "render_request",
]
