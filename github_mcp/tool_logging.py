"""Logging helpers for GitHub MCP tools.

Goals:
- Keep Render logs human-readable and clickable.
- Preserve structured metadata for debugging and metrics.
- Avoid circular imports between HTTP helpers and the MCP server.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import importlib.util

if importlib.util.find_spec("httpx") is not None:
    import httpx
else:
    class _HttpxResponseStub:
        headers: dict[str, str] = {}

        def __init__(self) -> None:
            self.request = None

    class _HttpxModuleStub:
        Response = _HttpxResponseStub

    httpx = _HttpxModuleStub()

from github_mcp.config import GITHUB_LOGGER
from github_mcp.metrics import _record_github_request as _record_github_request_metrics


def _sanitize_url_for_logs(raw: str) -> str:
    return (raw or "")



def _derive_github_web_url(api_url: str) -> Optional[str]:
    """Convert an api.github.com URL into a human-friendly github.com URL.

    Clicking raw GitHub API links in a browser frequently shows 404 (especially
    for private repos without auth). This helper generates an equivalent GitHub
    web URL so Render log links work for humans.
    """

    api_url = _sanitize_url_for_logs(api_url)

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
    api_url = _sanitize_url_for_logs(api_url)
    for prefix in ("https://api.github.com", "http://api.github.com"):
        if api_url.startswith(prefix):
            return api_url[len(prefix) :]
    return api_url


def _record_github_request(
    *,
    status_code: Optional[int],
    duration_ms: int,
    error: bool,
    resp: Optional[httpx.Response] = None,
    exc: Optional[BaseException] = None,
    method: Optional[str] = None,
    url: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Log GitHub request metadata and record metrics.

    This keeps compatibility with existing call sites while adding richer,
    user-friendly logging (method + URL + clickable web link).
    """

    # Infer request details when possible.
    if resp is not None and getattr(resp, "request", None) is not None:
        req = resp.request
        method = method or getattr(req, "method", None)
        if url is None:
            try:
                url = str(req.url)
            except Exception:  # pragma: no cover
                url = None

    log_extra: dict[str, Any] = {
        "status_code": status_code,
        "duration_ms": duration_ms,
        "error": error,
    }
    if method:
        log_extra["method"] = method
    if url:
        url = _sanitize_url_for_logs(url)
        log_extra["url"] = url
        web_url = _derive_github_web_url(url)
        if web_url:
            log_extra["web_url"] = _sanitize_url_for_logs(web_url)
    if resp is not None:
        log_extra["rate_limit_remaining"] = resp.headers.get("X-RateLimit-Remaining")
    if exc is not None:
        log_extra["exc_type"] = exc.__class__.__name__
    if extra:
        log_extra.update(extra)

    # Human-friendly message.
    status = status_code if status_code is not None else "ERR"
    method_s = method or "?"
    url_s = _shorten_api_url(url or "")
    msg = f"GitHub API {method_s} {url_s} -> {status} ({duration_ms}ms)"
    web_url_val = log_extra.get("web_url")
    if isinstance(web_url_val, str) and web_url_val:
        # Avoid URLs being the last token on the line. Some log viewers include
        # trailing quotes/punctuation in the detected hyperlink target.
        msg += f" | web: {web_url_val} [web]"

    GITHUB_LOGGER.info(msg, extra=log_extra)

    _record_github_request_metrics(
        status_code=status_code,
        duration_ms=duration_ms,
        error=error,
        resp=resp,
        exc=exc,
    )


__all__ = ["_record_github_request"]
