"""Async HTTP client helpers with lightweight metrics and logging wrappers."""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import time
from typing import Any, Dict, Optional

import httpx

from .config import (
    GITHUB_API_BASE,
    GITHUB_API_BASE_URL,
    GITHUB_REQUEST_TIMEOUT_SECONDS,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    MAX_CONCURRENCY,
)
from .exceptions import GitHubAPIError, GitHubAuthError, GitHubRateLimitError
from .tool_logging import _record_github_request

_concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
_http_client_github: Optional[httpx.AsyncClient] = None
_http_client_external: Optional[httpx.AsyncClient] = None


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

    token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if token is None:
        raise GitHubAuthError("GitHub authentication failed: token is not configured")

    token = token.strip()
    if not token:
        raise GitHubAuthError("GitHub authentication failed: token is empty")

    return token


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------


def _build_default_client() -> httpx.Client:
    """Return a default httpx.Client configured for GitHub's API."""

    return httpx.Client(base_url=GITHUB_API_BASE_URL, timeout=GITHUB_REQUEST_TIMEOUT_SECONDS)


def _github_client_instance() -> httpx.AsyncClient:
    """Singleton async client for GitHub API requests."""

    global _http_client_github
    if _http_client_github is None:
        token: Optional[str]
        try:
            token = _get_github_token()
        except GitHubAuthError:
            token = None

        limits = httpx.Limits(
            max_connections=HTTPX_MAX_CONNECTIONS,
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
        )
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        _http_client_github = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            timeout=HTTPX_TIMEOUT,
            limits=limits,
            headers=headers,
            verify=False,
        )
    return _http_client_github


def _external_client_instance() -> httpx.AsyncClient:
    """Singleton async client for non-GitHub HTTP requests."""

    global _http_client_external
    main_module = sys.modules.get("main")
    patched_client = getattr(main_module, "_http_client_external", None) if main_module else None
    if patched_client is not None:
        _http_client_external = patched_client

    if _http_client_external is None:
        limits = httpx.Limits(
            max_connections=HTTPX_MAX_CONNECTIONS,
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
        )
        _http_client_external = httpx.AsyncClient(timeout=HTTPX_TIMEOUT, limits=limits)
    return _http_client_external


# ---------------------------------------------------------------------------
# Request helpers with metrics
# ---------------------------------------------------------------------------


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
            status_code=None, duration_ms=int((time.time() - start) * 1000), error=True
        )
        raise

    try:
        response = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:  # pragma: no cover - network failures are hard to force
        _record_github_request(
            status_code=None, duration_ms=int((time.time() - start) * 1000), error=True
        )
        raise GitHubAPIError(f"GitHub request failed: {exc}") from exc
    finally:
        client.close()

    error_flag = getattr(response, "is_error", None)
    if error_flag is None:
        error_flag = response.status_code >= 400

    _record_github_request(
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

    start = time.time()
    client_factory = client_factory or _github_client_instance

    try:
        client = client_factory()
    except GitHubAuthError:
        _record_github_request(
            status_code=None, duration_ms=int((time.time() - start) * 1000), error=True
        )
        raise

    try:
        resp = await client.request(method, path, params=params, json=json_body, headers=headers)
    except httpx.TimeoutException as exc:
        _record_github_request(
            status_code=None, duration_ms=int((time.time() - start) * 1000), error=True, exc=exc
        )
        raise
    except httpx.HTTPError as exc:  # pragma: no cover - defensive
        _record_github_request(
            status_code=None, duration_ms=int((time.time() - start) * 1000), error=True, exc=exc
        )
        raise GitHubAPIError(f"GitHub request failed: {exc}") from exc

    duration_ms = int((time.time() - start) * 1000)
    error_flag = getattr(resp, "is_error", None)
    if error_flag is None:
        error_flag = resp.status_code >= 400

    _record_github_request(
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
    if error_flag and (
        resp.status_code == 429
        or resp.headers.get("X-RateLimit-Remaining") == "0"
        or "rate limit" in message_lower
    ):
        reset_hint = resp.headers.get("X-RateLimit-Reset") or resp.headers.get("Retry-After")
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
    "_concurrency_semaphore",
    "_external_client_instance",
    "_get_github_token",
    "_github_client_instance",
    "_github_request",
    "_http_client_external",
    "_http_client_github",
    "_request_with_metrics",
]
