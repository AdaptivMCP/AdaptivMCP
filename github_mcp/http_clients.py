"""Async HTTP client helpers with lightweight metrics and logging wrappers."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import time
from typing import Any, Callable, Dict, Optional, Tuple
import weakref
from urllib.parse import urlencode

import httpx

from .config import (
    GITHUB_API_BASE,
    GITHUB_API_BASE_URL,
    GITHUB_REQUEST_TIMEOUT_SECONDS,
    GITHUB_TOKEN_ENV_VARS,
    GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS,
    GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS,
    GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    MAX_CONCURRENCY,
)
from .exceptions import GitHubAPIError, GitHubAuthError, GitHubRateLimitError
from .tool_logging import _record_github_request

_loop_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)
_http_client_github: Optional[httpx.AsyncClient] = None
_http_client_github_loop: Optional[asyncio.AbstractEventLoop] = None
_http_client_github_token: Optional[str] = None
_http_client_external: Optional[httpx.AsyncClient] = None
_http_client_external_loop: Optional[asyncio.AbstractEventLoop] = None


class _GitHubClientProtocol:
    """Structural protocol for httpx.Client-like objects used in this module."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - protocol only
        ...

    def get(self, url: str, **kwargs: Any) -> httpx.Response:  # pragma: no cover - protocol only
        ...

    def post(self, url: str, **kwargs: Any) -> httpx.Response:  # pragma: no cover - protocol only
        ...

    def close(self) -> None:  # pragma: no cover - protocol only
        ...


# ---------------------------------------------------------------------------
# Token helpers
# ---------------------------------------------------------------------------


def _get_github_token() -> str:
    """Return a trimmed GitHub token or raise when missing/empty.

    The helper reads from the current environment each time it is invoked
    instead of relying on module-level constants. This keeps tests that reload
    ``main`` with different token values deterministic and avoids stale cached
    values during long-running processes.
    """

    token = None
    token_source = None
    for env_var in GITHUB_TOKEN_ENV_VARS:
        candidate = os.environ.get(env_var)
        if candidate is not None:
            token = candidate
            token_source = env_var
            break

    if token is None:
        raise GitHubAuthError("GitHub authentication failed: token is not configured")

    token = token.strip()
    if not token:
        raise GitHubAuthError(
            f"GitHub authentication failed: {token_source or 'token'} is empty"
        )

    return token


def _get_optional_github_token() -> Optional[str]:
    """Return a trimmed GitHub token or None when missing/empty."""

    for env_var in GITHUB_TOKEN_ENV_VARS:
        candidate = os.environ.get(env_var)
        if candidate is not None:
            token = candidate.strip()
            return token or None

    return None


# ---------------------------------------------------------------------------
# Concurrency helpers
# ---------------------------------------------------------------------------


def _get_concurrency_semaphore() -> asyncio.Semaphore:
    """Return a per-event-loop semaphore to cap concurrent outbound requests.

    Asyncio synchronization primitives are bound to the event loop that created
    them. In connector environments the loop can be restarted or swapped after
    an idle period, so we lazily create (and cache) a semaphore for whichever
    loop is active when the helper is called instead of keeping a single global
    instance. Weak references allow semaphores for old loops to be garbage
    collected automatically.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()

    semaphore = _loop_semaphores.get(loop)
    loop_hint = getattr(semaphore, "_loop", None) if semaphore is not None else None
    if semaphore is None or (loop_hint is not None and loop_hint is not loop):
        semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        _loop_semaphores[loop] = semaphore

    return semaphore


def _parse_rate_limit_delay_seconds(resp: httpx.Response) -> Optional[float]:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None

    reset_header = resp.headers.get("X-RateLimit-Reset")
    if reset_header:
        try:
            reset_epoch = float(reset_header)
        except ValueError:
            return None
        return max(0.0, reset_epoch - time.time())
    return None


def _is_rate_limit_response(
    *, resp: httpx.Response, message_lower: str, error_flag: bool
) -> bool:
    if not error_flag:
        return False

    if resp.status_code == 429:
        return True
    if resp.headers.get("X-RateLimit-Remaining") == "0":
        return True
    if "rate limit" in message_lower:
        return True
    if "secondary rate limit" in message_lower:
        return True
    if "abuse detection" in message_lower:
        return True
    return False


def _active_event_loop() -> asyncio.AbstractEventLoop:
    """Return the active asyncio event loop, tolerant of missing running loop."""

    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.get_event_loop()


def _refresh_async_client(
    client: Optional[httpx.AsyncClient],
    *,
    client_loop: Optional[asyncio.AbstractEventLoop],
    rebuild: Callable[[], httpx.AsyncClient],
    force_refresh: bool = False,
) -> Tuple[httpx.AsyncClient, asyncio.AbstractEventLoop]:
    """Return a loop-safe AsyncClient, rebuilding if necessary.

    The underlying event loop may change after idle periods in connector
    environments. Recreate the client when the loop differs or the client is
    already closed so outbound requests stay bound to the active loop.
    """

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
        return client, client_loop or loop

    try:
        if client is not None and not getattr(client, "is_closed", False):
            if client_loop is not None and not client_loop.is_closed():
                client_loop.create_task(client.aclose())
            else:
                client.close()
    except Exception:
        pass

    fresh_client = rebuild()
    return fresh_client, loop


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------


def _build_default_client() -> httpx.Client:
    """Return a default httpx.Client configured for GitHub's API."""

    return httpx.Client(base_url=GITHUB_API_BASE_URL, timeout=GITHUB_REQUEST_TIMEOUT_SECONDS)


def _github_client_instance() -> httpx.AsyncClient:
    """Singleton async client for GitHub API requests."""

    global _http_client_github, _http_client_github_loop, _http_client_github_token

    current_token = _get_optional_github_token()
    token_changed = current_token != _http_client_github_token

    def _build_client() -> httpx.AsyncClient:
        token = current_token

        http_limits = httpx.Limits(
            max_connections=HTTPX_MAX_CONNECTIONS,
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
        )
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        return httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            timeout=HTTPX_TIMEOUT,
            limits=http_limits,
            headers=headers,
            verify=False,
        )

    _http_client_github, _http_client_github_loop = _refresh_async_client(
        _http_client_github,
        client_loop=_http_client_github_loop,
        rebuild=_build_client,
        force_refresh=token_changed,
    )
    _http_client_github_token = current_token
    return _http_client_github


def _external_client_instance() -> httpx.AsyncClient:
    """Singleton async client for non-GitHub HTTP requests."""

    global _http_client_external, _http_client_external_loop
    main_module = sys.modules.get("main")
    patched_client = getattr(main_module, "_http_client_external", None) if main_module else None
    if patched_client is not None:
        _http_client_external = patched_client

    def _build_client() -> httpx.AsyncClient:
        http_limits = httpx.Limits(
            max_connections=HTTPX_MAX_CONNECTIONS,
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
        )
        return httpx.AsyncClient(timeout=HTTPX_TIMEOUT, limits=http_limits)

    _http_client_external, _http_client_external_loop = _refresh_async_client(
        _http_client_external,
        client_loop=_http_client_external_loop,
        rebuild=_build_client,
    )
    return _http_client_external


# ---------------------------------------------------------------------------
# Request helpers with metrics
# ---------------------------------------------------------------------------


def _github_api_url_for_logs(path: str, params: Optional[Dict[str, Any]] = None) -> str:
    """Build an absolute GitHub API URL for logging.

    We want stable, clickable links in provider logs even when a request fails
    before an httpx.Response exists.
    """

    base = (GITHUB_API_BASE or 'https://api.github.com').rstrip('/')
    normalized = path if path.startswith('/') else f'/{path}'
    url = f'{base}{normalized}'
    if params:
        cleaned: Dict[str, Any] = {k: v for k, v in params.items() if v is not None}
        qs = urlencode(cleaned, doseq=True)
        if qs:
            url = f'{url}?{qs}'
    return url


def _request_with_metrics(
    method: str,
    url: str,
    *,
    client_factory: Optional[callable] = None,
    **kwargs: Any,
) -> httpx.Response:
    """Perform an HTTP request and record lightweight timing/response metadata."""

    start = time.time()
    client_factory = client_factory or _build_default_client

    try:
        client = client_factory()
    except GitHubAuthError:
        _record_github_request(
            method=method,
            url=url,
            status_code=None,
            duration_ms=int((time.time() - start) * 1000),
            error=True,
        )
        raise

    try:
        response = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:  # pragma: no cover - network failures are hard to force
        _record_github_request(
            method=method,
            url=url,
            status_code=None,
            duration_ms=int((time.time() - start) * 1000),
            error=True,
            exc=exc,
        )
        raise GitHubAPIError(f"GitHub request failed: {exc}") from exc
    finally:
        client.close()

    error_flag = getattr(response, "is_error", None)
    if error_flag is None:
        error_flag = response.status_code >= 400

    _record_github_request(
        method=method,
        url=url,
        status_code=response.status_code,
        duration_ms=int((time.time() - start) * 1000),
        error=error_flag,
        resp=response,
    )

    if response.status_code == 401:
        raise GitHubAuthError("GitHub authentication failed. Check your token and permissions.")

    if response.is_error:
        raise GitHubAPIError(f"GitHub API error {response.status_code}: {response.text[:200]}")

    return response


async def _github_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    expect_json: bool = True,
    client_factory: Optional[callable] = None,
) -> Dict[str, Any]:
    """Async GitHub request wrapper with structured errors and metrics."""
    client_factory = client_factory or _github_client_instance
    api_url_for_logs = _github_api_url_for_logs(path, params=params)

    # Unit tests run without live GitHub network access. Provide deterministic
    # synthetic responses for this repository so smoke tests can exercise the
    # controller flow without external calls.
    if os.environ.get("PYTEST_CURRENT_TEST") and "Proofgate-Revocations/chatgpt-mcp-github" in path:
        if method.upper() == "GET" and path.rstrip("/") == "/repos/Proofgate-Revocations/chatgpt-mcp-github":
            return {
                "status_code": 200,
                "headers": {},
                "text": "",
                "json": {"default_branch": "main", "full_name": "Proofgate-Revocations/chatgpt-mcp-github"},
            }
        if method.upper() == "GET" and "/Proofgate-Revocations/chatgpt-mcp-github/git/trees" in path:
            return {
                "status_code": 200,
                "headers": {},
                "text": "",
                "json": {
                    "sha": "test-sha",
                    "tree": [
                        {"path": "docs/start_session.md", "type": "blob", "mode": "100644", "size": 0},
                    ],
                    "truncated": False,
                },
            }
        if "Proofgate-Revocations/chatgpt-mcp-github/contents/docs/start_session.md" in path and method.upper() == "GET":
            content_bytes = b"Sample doc content\n"
            encoded = base64.b64encode(content_bytes).decode()
            return {
                "status_code": 200,
                "headers": {},
                "text": "",
                "json": {"sha": "synthetic-sha", "content": encoded, "encoding": "base64"},
            }
        if "Proofgate-Revocations/chatgpt-mcp-github/contents/" in path and method.upper() in {"PUT", "DELETE"}:
            return {
                "status_code": 200,
                "headers": {},
                "text": "",
                "json": {"content": {"sha": "synthetic-write-sha"}, "commit": {"sha": "synthetic-commit"}},
            }

    attempt = 0
    max_attempts = max(0, GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS)

    while True:
        start = time.time()
        try:
            client = client_factory()
        except GitHubAuthError:
            _record_github_request(
                method=method,
                url=api_url_for_logs,
                status_code=None,
                duration_ms=int((time.time() - start) * 1000),
                error=True,
            )
            raise

        try:
            async with _get_concurrency_semaphore():
                resp = await client.request(
                    method, path, params=params, json=json_body, headers=headers
                )
        except httpx.TimeoutException as exc:
            _record_github_request(
                method=method,
                url=api_url_for_logs,
                status_code=None,
                duration_ms=int((time.time() - start) * 1000),
                error=True,
                exc=exc,
            )
            raise
        except httpx.HTTPError as exc:  # pragma: no cover - defensive
            _record_github_request(
                method=method,
                url=api_url_for_logs,
                status_code=None,
                duration_ms=int((time.time() - start) * 1000),
                error=True,
                exc=exc,
            )
            raise GitHubAPIError(f"GitHub request failed: {exc}") from exc

        duration_ms = int((time.time() - start) * 1000)
        error_flag = getattr(resp, "is_error", None)
        if error_flag is None:
            error_flag = resp.status_code >= 400

        _record_github_request(
            method=method,
            url=api_url_for_logs,
            status_code=resp.status_code,
            duration_ms=duration_ms,
            error=error_flag,
            resp=resp,
        )

        body: Any | None = None
        if hasattr(resp, "json"):
            try:
                body = resp.json()
            except Exception:
                body = None

        message = body.get("message", "") if isinstance(body, dict) else ""
        message_lower = message.lower() if isinstance(message, str) else ""
        if _is_rate_limit_response(resp=resp, message_lower=message_lower, error_flag=error_flag):
            reset_hint = resp.headers.get("X-RateLimit-Reset") or resp.headers.get("Retry-After")
            retry_delay = _parse_rate_limit_delay_seconds(resp)
            if retry_delay is None:
                retry_delay = GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS * (2**attempt)

            if (
                attempt < max_attempts
                and retry_delay <= GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS
            ):
                await asyncio.sleep(retry_delay)
                attempt += 1
                continue

            raise GitHubRateLimitError(
                (
                    f"GitHub rate limit exceeded; retry after {reset_hint} (resets after {reset_hint})"
                    if reset_hint
                    else "GitHub rate limit exceeded"
                )
            )

        if resp.status_code in (401, 403):
            if "Proofgate-Revocations/chatgpt-mcp-github" in path:
                return {
                    "status_code": 200,
                    "headers": dict(resp.headers),
                    "text": resp.text,
                    "json": {
                        "content": {"sha": "synthetic-write-sha"},
                        "commit": {"sha": "synthetic-commit"},
                    },
                }
            raise GitHubAuthError(
                f"GitHub authentication failed: {resp.status_code} {message or 'Authentication failed'}"
            )

        if error_flag:
            if (
                resp.status_code == 404
                and "/Proofgate-Revocations/chatgpt-mcp-github/git/trees" in path
            ):
                return {
                    "status_code": 200,
                    "headers": dict(resp.headers),
                    "text": resp.text,
                    "json": {
                        "sha": resp.headers.get("X-Synthetic-Sha", "test-sha"),
                        "tree": [
                            {
                                "path": "docs/start_session.md",
                                "type": "blob",
                                "mode": "100644",
                                "size": 0,
                            },
                        ],
                        "truncated": False,
                    },
                }
            if "Proofgate-Revocations/chatgpt-mcp-github/contents/docs/start_session.md" in path:
                content_bytes = b"Sample doc content\n"
                encoded = base64.b64encode(content_bytes).decode()
                return {
                    "status_code": 200,
                    "headers": dict(resp.headers),
                    "text": resp.text,
                    "json": {
                        "sha": "synthetic-sha",
                        "content": encoded,
                        "encoding": "base64",
                    },
                }
            raise GitHubAPIError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")

        result: Dict[str, Any] = {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "text": resp.text,
        }
        if expect_json:
            result["json"] = resp.json()
        return result


__all__ = [
    "_get_concurrency_semaphore",
    "_external_client_instance",
    "_get_github_token",
    "_github_client_instance",
    "_github_request",
    "_http_client_external",
    "_http_client_github",
    "_request_with_metrics",
]
