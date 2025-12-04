"""HTTP client helpers for GitHub and external requests."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, Mapping, Optional

import httpx

from . import config
from .exceptions import GitHubAPIError, GitHubAuthError, GitHubRateLimitError
from .metrics import _record_github_request

_http_client_github: Optional[httpx.AsyncClient] = None
_http_client_external: Optional[httpx.AsyncClient] = None
_concurrency_semaphore = asyncio.Semaphore(config.MAX_CONCURRENCY)


def _get_github_token() -> str:
    raw_token = config.GITHUB_PAT
    if not raw_token:
        raise GitHubAuthError(
            "GitHub token missing. Set GITHUB_PAT or GITHUB_TOKEN in the environment."
        )

    if not raw_token.startswith("github_"):
        if len(raw_token) <= 4 or raw_token[:4].lower() != "ghp_":
            raise GitHubAuthError("GitHub token missing 'github_' or 'ghp_' prefix")

    return raw_token


def _github_client_instance() -> httpx.AsyncClient:
    global _http_client_github  # pylint: disable=global-statement
    if _http_client_github is None:
        _http_client_github = httpx.AsyncClient(
            base_url=config.GITHUB_API_BASE,
            timeout=config.HTTPX_TIMEOUT,
            limits=httpx.Limits(
                max_connections=config.HTTPX_MAX_CONNECTIONS,
                max_keepalive_connections=config.HTTPX_MAX_KEEPALIVE,
            ),
            headers={
                "Authorization": f"Bearer {_get_github_token()}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "mcp-github-server",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
    return _http_client_github


def _external_client_instance() -> httpx.AsyncClient:
    global _http_client_external  # pylint: disable=global-statement
    if _http_client_external is None:
        _http_client_external = httpx.AsyncClient(
            timeout=config.HTTPX_TIMEOUT,
            limits=httpx.Limits(
                max_connections=config.HTTPX_MAX_CONNECTIONS,
                max_keepalive_connections=config.HTTPX_MAX_KEEPALIVE,
            ),
        )
    return _http_client_external


async def _github_request(
    method: str,
    path: str,
    *,
    params: Optional[Mapping[str, str]] = None,
    json_body: Optional[Mapping[str, Any]] = None,
    text_max_chars: Optional[int] = 1000,
    expect_json: bool = True,
    timeout: Optional[float] = None,
    raw_body: Optional[bytes] = None,
) -> Dict[str, Any]:
    start = time.time()

    try:
        client = _github_client_instance()
    except GitHubAuthError as exc:
        _record_github_request(
            status_code=None, duration_ms=int((time.time() - start) * 1000), error=True
        )
        raise

    try:
        async with _concurrency_semaphore:
            resp = await client.request(
                method,
                path,
                params=params,
                json=json_body,
                timeout=timeout,
                content=raw_body,
            )
    except httpx.TimeoutException as exc:  # pragma: no cover - network/slow
        duration_ms = int((time.time() - start) * 1000)
        _record_github_request(status_code=None, duration_ms=duration_ms, error=True, exc=exc)
        raise GitHubAPIError(f"GitHub {method} {path} timed out: {exc}")
    except httpx.HTTPError as exc:  # pragma: no cover - network errors
        duration_ms = int((time.time() - start) * 1000)
        _record_github_request(status_code=None, duration_ms=duration_ms, error=True, exc=exc)
        raise GitHubAPIError(f"GitHub {method} {path} failed: {exc}")

    duration_ms = int((time.time() - start) * 1000)
    base_payload: Dict[str, Any] = {
        "path": path,
        "method": method,
        "duration_ms": duration_ms,
        "status_code": resp.status_code,
    }

    if resp.status_code == 401:
        _record_github_request(
            status_code=resp.status_code,
            duration_ms=duration_ms,
            error=True,
            resp=resp,
            exc=None,
        )
        raise GitHubAuthError("GitHub authentication failed with status 401")

    if resp.status_code == 403 and "rate limit" in resp.text.lower():
        _record_github_request(
            status_code=resp.status_code,
            duration_ms=duration_ms,
            error=True,
            resp=resp,
            exc=None,
        )
        raise GitHubRateLimitError("GitHub rate limit exceeded")

    if resp.status_code >= 400:
        _record_github_request(
            status_code=resp.status_code,
            duration_ms=duration_ms,
            error=True,
            resp=resp,
            exc=None,
        )
        try:
            msg = resp.json().get("message", resp.text)
        except Exception:
            msg = resp.text
        raise GitHubAPIError(f"GitHub {method} {path} returned {resp.status_code}: {msg}")

    _record_github_request(
        status_code=resp.status_code,
        duration_ms=duration_ms,
        error=False,
        resp=resp,
        exc=None,
    )
    config.GITHUB_LOGGER.info("github_request", extra=base_payload)

    if expect_json:
        try:
            return {"status_code": resp.status_code, "json": resp.json()}
        except Exception:
            return {"status_code": resp.status_code, "json": None}

    text = resp.text if text_max_chars is None else resp.text[:text_max_chars]
    return {
        "status_code": resp.status_code,
        "text": text,
        "headers": dict(resp.headers),
    }


__all__ = [
    "_concurrency_semaphore",
    "_external_client_instance",
    "_get_github_token",
    "_github_client_instance",
    "_github_request",
    "_http_client_external",
    "_http_client_github",
]
