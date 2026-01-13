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
import os
import time
from typing import Any, Dict, Optional

from github_mcp.config import (
    BASE_LOGGER,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    LOG_RENDER_HTTP,
    LOG_RENDER_HTTP_BODIES,
    RENDER_API_BASE,
    RENDER_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS,
    RENDER_RATE_LIMIT_RETRY_MAX_ATTEMPTS,
    RENDER_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS,
    RENDER_TOKEN_ENV_VARS,
)
from github_mcp.exceptions import RenderAPIError, RenderAuthError
from github_mcp.http_clients import _get_concurrency_semaphore
from github_mcp.mcp_server.context import get_request_context

import importlib.util


if importlib.util.find_spec("httpx") is not None:  # pragma: no cover
    import httpx
else:  # pragma: no cover
    # The project vendors a fallback httpx shim in github_mcp.http_clients, but
    # Render API tools require httpx at runtime.
    httpx = None  # type: ignore[assignment]


_http_client_render: Optional["httpx.AsyncClient"] = None
_http_client_render_loop: Optional[asyncio.AbstractEventLoop] = None
_http_client_render_token: Optional[str] = None


def _active_event_loop() -> asyncio.AbstractEventLoop:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.get_event_loop()


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
    loop = _active_event_loop()

    needs_refresh = force_refresh or client is None
    if not needs_refresh:
        try:
            if client.is_closed:
                needs_refresh = True
        except Exception:
            needs_refresh = True

    if not needs_refresh and client_loop is not None and client_loop is not loop:
        needs_refresh = True

    if not needs_refresh:
        if client is None:
            needs_refresh = True
        else:
            return client, client_loop or loop

    try:
        if client is not None and not getattr(client, "is_closed", False):
            if client_loop is not None and not client_loop.is_closed():
                client_loop.create_task(client.aclose())
            else:
                try:
                    loop.create_task(client.aclose())
                except Exception:
                    try:
                        if not loop.is_closed() and not loop.is_running():
                            loop.run_until_complete(client.aclose())
                        else:
                            asyncio.run(client.aclose())
                    except Exception:
                        BASE_LOGGER.debug(
                            "Failed to close Render AsyncClient during refresh", exc_info=True
                        )
    except Exception:
        BASE_LOGGER.debug("Failed to refresh Render AsyncClient", exc_info=True)

    fresh_client = rebuild()
    return fresh_client, loop


def _render_client_instance() -> "httpx.AsyncClient":
    """Singleton async client for Render API requests."""

    global _http_client_render, _http_client_render_loop, _http_client_render_token

    current_token = _get_optional_render_token()
    token_changed = current_token != _http_client_render_token

    def _build_client() -> "httpx.AsyncClient":
        token = current_token or ""
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        limits = httpx.Limits(
            max_connections=HTTPX_MAX_CONNECTIONS,
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
        )
        return httpx.AsyncClient(
            base_url=RENDER_API_BASE,
            timeout=HTTPX_TIMEOUT,
            limits=limits,
            headers=headers,
        )

    _http_client_render, _http_client_render_loop = _refresh_async_client(
        _http_client_render,
        client_loop=_http_client_render_loop,
        rebuild=_build_client,
        force_refresh=token_changed,
    )
    _http_client_render_token = current_token
    return _http_client_render


def _parse_rate_limit_delay_seconds(resp: "httpx.Response") -> Optional[float]:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None

    reset_header = resp.headers.get("Ratelimit-Reset") or resp.headers.get("X-RateLimit-Reset")
    if reset_header:
        try:
            raw = float(reset_header)
        except ValueError:
            return None
        # Some APIs send an epoch timestamp, others send seconds-until-reset.
        if raw > 10_000_000_000:  # epoch milliseconds
            return max(0.0, (raw / 1000.0) - time.time())
        if raw > 1_000_000_000:  # epoch seconds
            return max(0.0, raw - time.time())
        return max(0.0, raw)

    return None


def _extract_response_body(resp: "httpx.Response") -> Any | None:
    try:
        return resp.json()
    except Exception:
        return None


def _build_response_payload(resp: "httpx.Response", *, body: Any | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status_code": getattr(resp, "status_code", None),
        "headers": dict(getattr(resp, "headers", {}) or {}),
    }
    if body is not None:
        payload["json"] = body
    else:
        payload["text"] = getattr(resp, "text", "")
    return payload


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
        try:
            resp = await _send_request(
                client,
                method=method,
                path=path,
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
            payload: Dict[str, Any] = {
                "event": "render_http",
                "request": dict(req) if isinstance(req, dict) else {},
                "method": str(method).upper(),
                "path": path,
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

            BASE_LOGGER.info(
                f"render_http method={str(method).upper()} path={path} status={getattr(resp, 'status_code', None)} duration_ms={duration_ms:.2f}",
                extra=payload,
            )

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
                await asyncio.sleep(retry_delay)
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
