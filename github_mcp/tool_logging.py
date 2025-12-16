"""Lightweight logging helpers for GitHub MCP tools.

This module centralizes structured logging for GitHub HTTP requests while
re-exporting the metrics hook used throughout the codebase. Keeping the logic
here avoids circular imports between http client helpers and the broader server
module.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from github_mcp.config import GITHUB_LOGGER
from github_mcp.metrics import _record_github_request as _record_github_request_metrics


def _derive_github_web_url(api_url: str) -> Optional[str]:
    """Convert an api.github.com URL into a human-friendly github.com URL.

    This is primarily used so Render logs contain clickable links that work for
    humans without requiring an API token (the GitHub API returns 404 for private
    repos when unauthenticated).
    """

    try:
        parsed = urlparse(api_url)
    except Exception:  # pragma: no cover
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 3 or parts[0] != "repos":
        return None

    full_name = f"{parts[1]}/{parts[2]}"

    # /repos/{owner}/{repo}/contents/{path}?ref={ref}
    if len(parts) >= 5 and parts[3] == "contents":
        file_path = "/".join(parts[4:])
        ref = parse_qs(parsed.query).get("ref", ["main"])[0]
        return f"https://github.com/{full_name}/blob/{ref}/{file_path}"

    # Fallback: show repo root.
    return f"https://github.com/{full_name}"


def _shorten_api_url(api_url: str) -> str:
    for prefix in ("https://api.github.com", "http://api.github.com"):
        if api_url.startswith(prefix):
            return api_url[len(prefix) :]
    return api_url


def _record_github_request(
    *,
    method: Optional[str] = None,
    url: Optional[str] = None,
    status_code: Optional[int],
    duration_ms: int,
    error: bool,
    resp: Optional[httpx.Response] = None,
    exc: Optional[BaseException] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Log GitHub request metadata and record metrics."""

    log_extra: dict[str, Any] = {
        "status_code": status_code,
        "duration_ms": duration_ms,
        "error": error,
    }
    if method:
        log_extra["method"] = method
    if url:
        log_extra["url"] = url
        web_url = _derive_github_web_url(url)
        if web_url:
            log_extra["web_url"] = web_url
    if resp is not None:
        log_extra["rate_limit_remaining"] = resp.headers.get("X-RateLimit-Remaining")
    if exc is not None:
        log_extra["exc_type"] = exc.__class__.__name__
    if extra:
        log_extra.update(extra)

    # Make Render logs readable without requiring JSON expansion.
    status = status_code if status_code is not None else "ERR"
    method_s = method or "?"
    url_s = _shorten_api_url(url or "")
    msg = f"GitHub API {method_s} {url_s} -> {status} ({duration_ms}ms)"
    if url:
        web_url = log_extra.get("web_url")
        if isinstance(web_url, str) and web_url:
            msg += f" | web: {web_url}"

    GITHUB_LOGGER.info(msg, extra=log_extra)
    _record_github_request_metrics(
        status_code=status_code,
        duration_ms=duration_ms,
        error=error,
        resp=resp,
        exc=exc,
    )


__all__ = ["_record_github_request"]
