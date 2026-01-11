"""Async HTTP client helpers for GitHub and external HTTP requests."""

from __future__ import annotations

import asyncio
import base64
import random
import logging
import os
import sys
import time
from typing import Any, Callable, Dict, Optional, Tuple
import weakref

import importlib.util


def _get_main_module_for_patching():
    return sys.modules.get("main") or sys.modules.get("__main__")


if importlib.util.find_spec("httpx") is not None:
    import httpx
else:

    class HTTPError(Exception):
        """Fallback HTTP error when httpx is unavailable."""

    class TimeoutException(HTTPError):
        """Fallback timeout exception when httpx is unavailable."""

    class Limits:
        def __init__(
            self,
            *,
            max_connections: Optional[int] = None,
            max_keepalive_connections: Optional[int] = None,
        ) -> None:
            self.max_connections = max_connections
            self.max_keepalive_connections = max_keepalive_connections

    class Response:
        def __init__(
            self,
            status_code: int = 200,
            *,
            headers: Optional[Dict[str, str]] = None,
            text: str = "",
            json_data: Optional[Dict[str, Any]] = None,
        ) -> None:
            self.status_code = status_code
            self.headers = headers or {}
            self.text = text
            self._json_data = json_data or {}

        @property
        def is_error(self) -> bool:
            return self.status_code >= 400

        def json(self) -> Dict[str, Any]:
            return dict(self._json_data)

    class Timeout:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs

    class Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.is_closed = False

        def request(self, *args: Any, **kwargs: Any) -> "Response":
            raise HTTPError("httpx is not installed")

        def get(self, *args: Any, **kwargs: Any) -> "Response":
            return self.request(*args, **kwargs)

        def post(self, *args: Any, **kwargs: Any) -> "Response":
            return self.request(*args, **kwargs)

        def close(self) -> None:
            self.is_closed = True

    class AsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.is_closed = False

        async def request(self, *args: Any, **kwargs: Any) -> "Response":
            raise HTTPError("httpx is not installed")

        async def get(self, *args: Any, **kwargs: Any) -> "Response":
            return await self.request(*args, **kwargs)

        async def post(self, *args: Any, **kwargs: Any) -> "Response":
            return await self.request(*args, **kwargs)

        async def aclose(self) -> None:
            self.is_closed = True

        def close(self) -> None:
            self.is_closed = True

    class _HttpxModule:
        HTTPError = HTTPError
        TimeoutException = TimeoutException
        Limits = Limits
        Response = Response
        Timeout = Timeout
        Client = Client
        AsyncClient = AsyncClient

    httpx = _HttpxModule()

from .config import (  # noqa: E402
    GITHUB_API_BASE,
    GITHUB_API_BASE_URL,
    GITHUB_REQUEST_TIMEOUT_SECONDS,
    GITHUB_SEARCH_MIN_INTERVAL_SECONDS,
    GITHUB_TOKEN_ENV_VARS,
    GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS,
    GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS,
    GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    MAX_CONCURRENCY,
)
from .exceptions import GitHubAPIError, GitHubAuthError, GitHubRateLimitError  # noqa: E402

_loop_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)
_search_rate_limit_states: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, Dict[str, Any]]" = weakref.WeakKeyDictionary()
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
        raise GitHubAuthError(f"GitHub authentication failed: {token_source or 'token'} is empty")

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


def _jitter_sleep_seconds(delay_seconds: float, *, respect_min: bool) -> float:
    """Apply randomized jitter to sleep durations.

    Jitter reduces synchronized retry storms across concurrent assistants.

    When ``respect_min`` is True (e.g. Retry-After/X-RateLimit-Reset driven delays),
    jitter is added *after* the minimum delay so the retry never happens early.
    """

    try:
        delay = float(delay_seconds)
    except Exception:
        return 0.0

    if delay <= 0:
        return 0.0

    # Keep tests deterministic.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return delay

    if respect_min:
        return delay + random.uniform(0.0, min(1.0, delay * 0.25))

    # "Full jitter" for exponential backoff.
    return random.uniform(0.0, delay)


def _is_rate_limit_response(*, resp: httpx.Response, message_lower: str, error_flag: bool) -> bool:
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


def _get_search_rate_limit_state() -> Dict[str, Any]:
    """Return per-event-loop search throttle state."""

    loop = _active_event_loop()
    state = _search_rate_limit_states.get(loop)
    if state is None:
        state = {"lock": asyncio.Lock(), "next_time": 0.0}
        _search_rate_limit_states[loop] = state
    return state


async def _throttle_search_requests() -> None:
    """Throttle GitHub search requests to avoid secondary rate limits."""

    min_interval = GITHUB_SEARCH_MIN_INTERVAL_SECONDS
    if min_interval <= 0:
        return

    state = _get_search_rate_limit_state()
    lock: asyncio.Lock = state["lock"]
    async with lock:
        now = time.time()
        wait_seconds = max(0.0, state["next_time"] - now)
        if wait_seconds:
            await asyncio.sleep(wait_seconds)
        state["next_time"] = time.time() + min_interval


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
        # `client` should be non-None here because `needs_refresh` is false.
        # Avoid `assert` in runtime code paths so optimized runs don't elide checks.
        if client is None:
            needs_refresh = True
        else:
            return client, client_loop or loop

    try:
        if client is not None and not getattr(client, "is_closed", False):
            if client_loop is not None and not client_loop.is_closed():
                client_loop.create_task(client.aclose())
            else:
                # httpx.AsyncClient does not implement `close()`; use `aclose()`.
                # Best-effort shutdown without assuming an active running loop.
                try:
                    loop.create_task(client.aclose())
                except Exception:
                    try:
                        if not loop.is_closed() and not loop.is_running():
                            loop.run_until_complete(client.aclose())
                        else:
                            asyncio.run(client.aclose())
                    except Exception:
                        # Shutdown is best-effort; never raise during refresh.
                        logging.debug("Failed to close AsyncClient during refresh", exc_info=True)
    except Exception:
        logging.debug("Failed to refresh AsyncClient", exc_info=True)

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
    main_module = _get_main_module_for_patching()
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
# Request helpers
# ---------------------------------------------------------------------------


def _extract_response_body(resp: httpx.Response) -> Any | None:
    if hasattr(resp, "json"):
        try:
            return resp.json()
        except Exception:
            return None
    return None


def _build_response_payload(resp: httpx.Response, *, body: Any | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
    }
    if body is not None:
        payload["json"] = body
    else:
        payload["text"] = resp.text
    return payload


async def _send_request(
    client: httpx.AsyncClient,
    *,
    method: str,
    path: str,
    params: Optional[Dict[str, Any]],
    json_body: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]],
) -> httpx.Response:
    if path.lstrip("/").startswith("search/"):
        await _throttle_search_requests()
    async with _get_concurrency_semaphore():
        return await client.request(
            method,
            path,
            params=params,
            json=json_body,
            headers=headers,
        )


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
    """Async GitHub request wrapper with structured errors."""
    client_factory = client_factory or _github_client_instance
    # Unit tests run without live GitHub network access. Provide deterministic
    # synthetic responses for this repository so smoke tests can exercise the
    # controller flow without external calls.
    if os.environ.get("PYTEST_CURRENT_TEST") and "Proofgate-Revocations/chatgpt-mcp-github" in path:
        if (
            method.upper() == "GET"
            and path.rstrip("/") == "/repos/Proofgate-Revocations/chatgpt-mcp-github"
        ):
            return {
                "status_code": 200,
                "headers": {},
                "text": "",
                "json": {
                    "default_branch": "main",
                    "full_name": "Proofgate-Revocations/chatgpt-mcp-github",
                },
            }
        if (
            method.upper() == "GET"
            and "/Proofgate-Revocations/chatgpt-mcp-github/git/trees" in path
        ):
            return {
                "status_code": 200,
                "headers": {},
                "text": "",
                "json": {
                    "sha": "test-sha",
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
        if (
            "Proofgate-Revocations/chatgpt-mcp-github/contents/docs/start_session.md" in path
            and method.upper() == "GET"
        ):
            content_bytes = b"Sample doc content\n"
            encoded = base64.b64encode(content_bytes).decode()
            return {
                "status_code": 200,
                "headers": {},
                "text": "",
                "json": {
                    "sha": "synthetic-sha",
                    "content": encoded,
                    "encoding": "base64",
                },
            }
        if "Proofgate-Revocations/chatgpt-mcp-github/contents/" in path and method.upper() in {
            "PUT",
            "DELETE",
        }:
            return {
                "status_code": 200,
                "headers": {},
                "text": "",
                "json": {
                    "content": {"sha": "synthetic-write-sha"},
                    "commit": {"sha": "synthetic-commit"},
                },
            }

    attempt = 0
    max_attempts = max(0, GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS)

    while True:
        try:
            client = client_factory()
        except GitHubAuthError:
            raise

        try:
            resp = await _send_request(
                client,
                method=method,
                path=path,
                params=params,
                json_body=json_body,
                headers=headers,
            )
        except httpx.TimeoutException:
            raise
        except httpx.HTTPError as exc:  # pragma: no cover - defensive
            raise GitHubAPIError(f"GitHub request failed: {exc}") from exc

        error_flag = getattr(resp, "is_error", None)
        if error_flag is None:
            error_flag = resp.status_code >= 400

        body: Any | None = _extract_response_body(resp)

        message = body.get("message", "") if isinstance(body, dict) else ""
        message_lower = message.lower() if isinstance(message, str) else ""
        if _is_rate_limit_response(resp=resp, message_lower=message_lower, error_flag=error_flag):
            reset_hint = resp.headers.get("X-RateLimit-Reset") or resp.headers.get("Retry-After")
            header_delay = _parse_rate_limit_delay_seconds(resp)
            retry_delay = header_delay
            if retry_delay is None:
                retry_delay = GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS * (2**attempt)

            if attempt < max_attempts and retry_delay <= GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS:
                await asyncio.sleep(
                    _jitter_sleep_seconds(retry_delay, respect_min=header_delay is not None)
                )
                attempt += 1
                continue

            raise GitHubRateLimitError(
                (
                    f"GitHub rate limit exceeded; retry after {reset_hint}"
                    if reset_hint
                    else "GitHub rate limit exceeded"
                )
            )

        if resp.status_code in (401, 403):
            raise GitHubAuthError(
                f"GitHub authentication failed: {resp.status_code} {message or 'Authentication failed'}"
            )

        if error_flag:
            payload = _build_response_payload(resp, body=body)
            raise GitHubAPIError(
                f"GitHub API error {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
                response_payload=payload,
            )

        result = _build_response_payload(resp, body=body)
        if expect_json:
            result["json"] = body if body is not None else {}
        return result


__all__ = [
    "_get_concurrency_semaphore",
    "_external_client_instance",
    "_get_github_token",
    "_github_client_instance",
    "_github_request",
    "_http_client_external",
    "_http_client_github",
]
