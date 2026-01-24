"""Render API client helpers.

This module provides a thin, well-instrumented wrapper around Render's public
API for use by MCP tools.

Design goals:
- No synthetic payloads in production.
- Tool outputs contain the real Render responses (no truncation).
- Provider logs are human-readable and correlate with inbound tool calls.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
from typing import Any

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
from github_mcp.mcp_server.decorators import (
    ANSI_CYAN,
    ANSI_DIM,
    ANSI_GREEN,
    ANSI_RED,
    ANSI_YELLOW,
    LOG_TOOL_COLOR,
    _ansi,
    _preview_render_logs,
    _truncate_text,
)

if importlib.util.find_spec("httpx") is not None:  # pragma: no cover
    import httpx
else:  # pragma: no cover
    # The project vendors a fallback httpx shim in github_mcp.http_clients, but
    # Render API tools require httpx at runtime.
    httpx = None  # type: ignore[assignment]


_http_client_render: httpx.AsyncClient | None = None
_http_client_render_loop: asyncio.AbstractEventLoop | None = None
_http_client_render_token: str | None = None
_http_client_render_base: str | None = None
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
        raise RenderAuthError(
            f"Render authentication failed: {token_source or 'token'} is empty"
        )

    return token


def _get_optional_render_token() -> str | None:
    for env_var in RENDER_TOKEN_ENV_VARS:
        candidate = os.environ.get(env_var)
        if candidate is not None:
            token = candidate.strip()
            return token or None
    return None


def _render_token_source() -> str | None:
    """Return the env var name providing the Render token, if any."""

    for env_var in RENDER_TOKEN_ENV_VARS:
        candidate = os.environ.get(env_var)
        if candidate is not None:
            return env_var
    return None


def _safe_render_headers(headers: dict[str, str] | None) -> dict[str, str] | None:
    if not headers:
        return None
    return {k: v for k, v in headers.items() if k and k.lower() != "authorization"}


def _render_http_header(
    kind: str, method: str, path: str, *, inline_ctx: str = ""
) -> str:
    """Human-readable, colored header for Render HTTP logs."""

    verb = str(method).upper()
    p = str(path)
    if LOG_TOOL_COLOR:
        head = (
            _ansi(kind, ANSI_CYAN)
            + " "
            + _ansi(verb, ANSI_GREEN)
            + " "
            + _ansi(p, ANSI_CYAN)
        )
        if inline_ctx:
            head = head + " " + _ansi(inline_ctx, ANSI_DIM)
        return head
    head = f"{kind} {verb} {p}"
    if inline_ctx:
        head = head + " " + inline_ctx
    return head


def _log_render_http(
    *,
    level: str,
    msg: str,
    extra: dict[str, Any],
) -> None:
    if not LOG_RENDER_HTTP:
        return

    # Info-only logging policy: always emit INFO.
    BASE_LOGGER.info(msg, extra=extra)


def _refresh_async_client(
    client: httpx.AsyncClient | None,
    *,
    client_loop: asyncio.AbstractEventLoop | None,
    rebuild,
    force_refresh: bool = False,
):
    from .async_utils import refresh_async_client

    def _log_debug(msg: str) -> None:
        BASE_LOGGER.info(msg)

    def _log_debug_exc(msg: str) -> None:
        BASE_LOGGER.info(msg, exc_info=True)

    refreshed, loop = refresh_async_client(
        client,
        client_loop=client_loop,
        rebuild=rebuild,
        force_refresh=force_refresh,
        log_debug=_log_debug,
        log_debug_exc=_log_debug_exc,
    )
    return refreshed, loop


def _render_client_instance() -> httpx.AsyncClient:
    """Singleton async client for Render API requests."""

    global \
        _http_client_render, \
        _http_client_render_loop, \
        _http_client_render_token, \
        _http_client_render_base, \
        _render_api_version_prefix

    current_token = _get_optional_render_token()
    token_changed = current_token != _http_client_render_token

    normalized_base, _version_prefix = _normalize_render_api_base(RENDER_API_BASE)
    base_changed = normalized_base != _http_client_render_base

    def _build_client() -> httpx.AsyncClient:
        token = current_token or ""
        # Keep base/path composition stable regardless of whether RENDER_API_BASE includes /v1.
        nonlocal normalized_base, _version_prefix
        _render_api_version_prefix = _version_prefix
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


def _parse_rate_limit_delay_seconds(resp: httpx.Response) -> float | None:
    from .http_utils import parse_rate_limit_delay_seconds

    return parse_rate_limit_delay_seconds(
        resp,
        reset_header_names=("Ratelimit-Reset", "X-RateLimit-Reset"),
        allow_epoch_millis=True,
        allow_duration_seconds=True,
    )


def _extract_response_body(resp: httpx.Response) -> Any | None:
    from .http_utils import extract_response_json

    return extract_response_json(resp)


def _build_response_payload(
    resp: httpx.Response, *, body: Any | None = None
) -> dict[str, Any]:
    # Backward-compatible wrapper for shared response payload builder.
    from github_mcp.http_utils import build_response_payload

    return build_response_payload(resp, body=body)


async def _send_request(
    client: httpx.AsyncClient,
    *,
    method: str,
    path: str,
    params: dict[str, Any] | None,
    json_body: Any | None,
    headers: dict[str, str] | None,
) -> httpx.Response:
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
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    headers: dict[str, str] | None = None,
    expect_json: bool = True,
    require_auth: bool = True,
) -> dict[str, Any]:
    """Async Render request wrapper with structured errors and logging."""

    if require_auth:
        _get_render_token()

    attempt = 0
    max_attempts = max(0, RENDER_RATE_LIMIT_RETRY_MAX_ATTEMPTS)

    req = get_request_context()
    inline_ctx = ""
    if LOG_INLINE_CONTEXT:
        try:
            inline_ctx = format_log_context(req)
        except Exception:
            inline_ctx = ""

    token_source = _render_token_source()
    normalized_base, version_prefix = _normalize_render_api_base(RENDER_API_BASE)
    effective_path = _apply_render_version_prefix(path)

    # START (dev-facing)
    if LOG_RENDER_HTTP:
        bits = []
        bits.append(
            _render_http_header("RENDER", method, effective_path, inline_ctx=inline_ctx)
        )
        if normalized_base:
            bits.append(
                _ansi(f"base={normalized_base}", ANSI_DIM)
                if LOG_TOOL_COLOR
                else f"base={normalized_base}"
            )
        if token_source:
            bits.append(
                _ansi(f"token={token_source}", ANSI_DIM)
                if LOG_TOOL_COLOR
                else f"token={token_source}"
            )
        if params:
            bits.append(
                _ansi(f"params={_truncate_text(params, limit=220)}", ANSI_DIM)
                if LOG_TOOL_COLOR
                else f"params={_truncate_text(params, limit=220)}"
            )
        if json_body:
            bits.append(
                _ansi(f"json={_truncate_text(json_body, limit=220)}", ANSI_DIM)
                if LOG_TOOL_COLOR
                else f"json={_truncate_text(json_body, limit=220)}"
            )
        safe_headers = _safe_render_headers(headers)
        if safe_headers:
            bits.append(
                _ansi(f"headers={_truncate_text(safe_headers, limit=220)}", ANSI_DIM)
                if LOG_TOOL_COLOR
                else f"headers={_truncate_text(safe_headers, limit=220)}"
            )
        _log_render_http(
            level="info",
            msg="\n".join(bits),
            extra={
                "event": "render_http_started",
                "request": summarize_request_context(req)
                if isinstance(req, dict)
                else {},
                "log_context": inline_ctx or None,
                "method": str(method).upper(),
                "path": effective_path,
                "base": normalized_base,
                "token_source": token_source,
                "params": params,
                "json_body": json_body,
                "headers": safe_headers,
            },
        )

    while True:
        started = time.perf_counter()
        client = _render_client_instance()
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
            duration_ms = (time.perf_counter() - started) * 1000
            _log_render_http(
                level="error",
                msg=(
                    _render_http_header(
                        "RENDER_FAIL", method, effective_path, inline_ctx=inline_ctx
                    )
                    + " "
                    + (
                        _ansi(f"({duration_ms:.0f}ms)", ANSI_DIM)
                        if LOG_TOOL_COLOR
                        else f"({duration_ms:.0f}ms)"
                    )
                    + "\n"
                    + (_ansi(str(exc), ANSI_RED) if LOG_TOOL_COLOR else str(exc))
                ),
                extra={
                    "event": "render_http_exception",
                    "request": summarize_request_context(req)
                    if isinstance(req, dict)
                    else {},
                    "log_context": inline_ctx or None,
                    "method": str(method).upper(),
                    "path": effective_path,
                    "duration_ms": duration_ms,
                    "attempt": attempt,
                    "exception_type": exc.__class__.__name__,
                },
            )
            raise RenderAPIError(f"Render request failed: {exc}") from exc

        body: Any | None = _extract_response_body(resp)
        error_flag = getattr(resp, "is_error", None)
        if error_flag is None:
            error_flag = getattr(resp, "status_code", 0) >= 400

        duration_ms = (time.perf_counter() - started) * 1000
        status_code = getattr(resp, "status_code", 0)

        # END (dev-facing)
        if LOG_RENDER_HTTP:
            lvl = "info"
            if status_code >= 500:
                lvl = "error"
            elif status_code >= 400:
                lvl = "warning"

            status_txt = str(status_code)
            if LOG_TOOL_COLOR:
                if status_code >= 500:
                    status_txt = _ansi(status_txt, ANSI_RED)
                elif status_code >= 400:
                    status_txt = _ansi(status_txt, ANSI_YELLOW)
                else:
                    status_txt = _ansi(status_txt, ANSI_GREEN)

            # Highlight rate limit headers when present.
            resp_headers = dict(getattr(resp, "headers", {}) or {})
            rl_remaining = resp_headers.get("Ratelimit-Remaining") or resp_headers.get(
                "X-RateLimit-Remaining"
            )
            rl_reset = resp_headers.get("Ratelimit-Reset") or resp_headers.get(
                "X-RateLimit-Reset"
            )
            rl_bits: list[str] = []
            if rl_remaining is not None:
                rl_bits.append(f"remaining={rl_remaining}")
            if rl_reset is not None:
                rl_bits.append(f"reset={rl_reset}")
            rl = ("rate_limit " + ", ".join(rl_bits)) if rl_bits else ""
            rl = _ansi(rl, ANSI_DIM) if (rl and LOG_TOOL_COLOR) else rl

            line = (
                _render_http_header(
                    "RENDER_RES", method, effective_path, inline_ctx=inline_ctx
                )
                + " "
                + status_txt
                + " "
                + (
                    _ansi(f"({duration_ms:.0f}ms)", ANSI_DIM)
                    if LOG_TOOL_COLOR
                    else f"({duration_ms:.0f}ms)"
                )
            )
            if attempt:
                line += " " + (
                    _ansi(f"attempt={attempt + 1}", ANSI_DIM)
                    if LOG_TOOL_COLOR
                    else f"attempt={attempt + 1}"
                )
            if rl:
                line += " " + rl

            # Only print a body preview by default for /logs; other endpoints can be noisy.
            body_lines: list[str] = []
            if effective_path.endswith("/logs"):
                items: Any | None = None
                if isinstance(body, list):
                    items = body
                elif isinstance(body, dict):
                    # Some proxies/wrappers may nest logs under common keys.
                    if isinstance(body.get("json"), list):
                        items = body.get("json")
                    elif isinstance(body.get("logs"), list):
                        items = body.get("logs")
                    elif isinstance(body.get("items"), list):
                        items = body.get("items")
                if isinstance(items, list) and items:
                    try:
                        body_lines.append(_preview_render_logs(items))
                    except Exception:
                        pass
            if LOG_RENDER_HTTP_BODIES and not body_lines:
                preview = body if body is not None else getattr(resp, "text", "")
                body_lines.append(
                    _ansi("body", ANSI_CYAN)
                    + "\n"
                    + _truncate_text(preview, limit=2000)
                    if LOG_TOOL_COLOR
                    else "body\n" + _truncate_text(preview, limit=2000)
                )

            msg = line if not body_lines else (line + "\n" + "\n".join(body_lines))

            payload: dict[str, Any] = {
                "event": "render_http_completed",
                "request": summarize_request_context(req)
                if isinstance(req, dict)
                else {},
                "log_context": inline_ctx or None,
                "method": str(method).upper(),
                "path": effective_path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "attempt": attempt,
            }
            if params is not None:
                payload["params"] = params
            if json_body is not None:
                payload["json_body"] = json_body
            safe_headers = _safe_render_headers(headers)
            if safe_headers is not None:
                payload["headers"] = safe_headers
            if LOG_RENDER_HTTP_BODIES:
                payload["response_headers"] = resp_headers
                payload["response_body"] = (
                    body if body is not None else getattr(resp, "text", "")
                )
            _log_render_http(level=lvl, msg=msg, extra=payload)
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

            if (
                attempt < max_attempts
                and retry_delay <= RENDER_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS
            ):
                # Apply jitter to reduce synchronized retry storms.
                from .retry_utils import jitter_sleep_seconds

                # Developer-facing retry line.
                if LOG_RENDER_HTTP:
                    delay = jitter_sleep_seconds(
                        retry_delay,
                        respect_min=header_delay is not None,
                        cap_seconds=1.0,
                    )
                    msg = (
                        _render_http_header(
                            "RENDER_RETRY",
                            method,
                            effective_path,
                            inline_ctx=inline_ctx,
                        )
                        + " "
                        + (_ansi("429", ANSI_YELLOW) if LOG_TOOL_COLOR else "429")
                        + " "
                        + (
                            _ansi(f"sleep={delay:.2f}s", ANSI_DIM)
                            if LOG_TOOL_COLOR
                            else f"sleep={delay:.2f}s"
                        )
                        + " "
                        + (
                            _ansi(f"attempt={attempt + 1}/{max_attempts + 1}", ANSI_DIM)
                            if LOG_TOOL_COLOR
                            else f"attempt={attempt + 1}/{max_attempts + 1}"
                        )
                    )
                    _log_render_http(
                        level="warning",
                        msg=msg,
                        extra={
                            "event": "render_http_retry",
                            "request": summarize_request_context(req)
                            if isinstance(req, dict)
                            else {},
                            "log_context": inline_ctx or None,
                            "method": str(method).upper(),
                            "path": effective_path,
                            "status_code": 429,
                            "retry_delay_seconds": delay,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                        },
                    )

                delay = jitter_sleep_seconds(
                    retry_delay,
                    respect_min=header_delay is not None,
                    cap_seconds=1.0,
                )

                await asyncio.sleep(delay)
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
