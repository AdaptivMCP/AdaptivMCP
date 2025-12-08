"""Lightweight logging helpers for GitHub MCP tools.

This module centralizes structured logging for GitHub HTTP requests while
re-exporting the metrics hook used throughout the codebase. Keeping the logic
here avoids circular imports between http client helpers and the broader server
module.
"""

from __future__ import annotations

from typing import Optional

import httpx

from github_mcp.config import GITHUB_LOGGER
from github_mcp.metrics import _record_github_request as _record_github_request_metrics


def _record_github_request(
    *,
    status_code: Optional[int],
    duration_ms: int,
    error: bool,
    resp: Optional[httpx.Response] = None,
    exc: Optional[BaseException] = None,
) -> None:
    """Log GitHub request metadata and record metrics.

    The helper mirrors the signature expected by :mod:`github_mcp.http_clients`
    while delegating the counter updates to :func:`github_mcp.metrics.
    _record_github_request`. It also emits a structured log line so callers can
    trace request outcomes during development and in production logs.
    """

    extra = {
        "status_code": status_code,
        "duration_ms": duration_ms,
        "error": error,
    }
    if resp is not None:
        extra["rate_limit_remaining"] = resp.headers.get("X-RateLimit-Remaining")
    if exc is not None:
        extra["exc_type"] = exc.__class__.__name__

    GITHUB_LOGGER.info("github_request", extra=extra)
    _record_github_request_metrics(
        status_code=status_code,
        duration_ms=duration_ms,
        error=error,
        resp=resp,
        exc=exc,
    )


__all__ = ["_record_github_request"]
