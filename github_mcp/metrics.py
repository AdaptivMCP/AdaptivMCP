"""In-process metrics registry for GitHub MCP tools."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx


def _new_metrics_state() -> Dict[str, Any]:
    return {
        "tools": {},
        "github": {
            "requests_total": 0,
            "errors_total": 0,
            "rate_limit_events_total": 0,
            "timeouts_total": 0,
        },
    }


_METRICS: Dict[str, Any] = _new_metrics_state()


def _reset_metrics_for_tests() -> None:
    """Reset in-process metrics; intended for tests."""

    _METRICS.clear()
    _METRICS.update(_new_metrics_state())


def _record_tool_call(
    tool_name: str,
    *,
    write_action: bool,
    duration_ms: int,
    errored: bool,
) -> None:
    tools_bucket = _METRICS.setdefault("tools", {})
    bucket = tools_bucket.setdefault(
        tool_name,
        {
            "calls_total": 0,
            "errors_total": 0,
            "write_calls_total": 0,
            "latency_ms_sum": 0,
        },
    )
    bucket["calls_total"] += 1
    if write_action:
        bucket["write_calls_total"] += 1
    bucket["latency_ms_sum"] += max(0, int(duration_ms))
    if errored:
        bucket["errors_total"] += 1


def _record_github_request(
    *,
    status_code: Optional[int],
    duration_ms: int,
    error: bool,
    resp: Optional[httpx.Response] = None,
    exc: Optional[BaseException] = None,
) -> None:
    github_bucket = _METRICS.setdefault("github", {})
    github_bucket["requests_total"] = github_bucket.get("requests_total", 0) + 1
    if error:
        github_bucket["errors_total"] = github_bucket.get("errors_total", 0) + 1

    if resp is not None:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        incremented = False
        if remaining is not None:
            try:
                if int(remaining) <= 0:
                    github_bucket["rate_limit_events_total"] = (
                        github_bucket.get("rate_limit_events_total", 0) + 1
                    )
                    incremented = True
            except ValueError:
                pass

        if resp.status_code == 429 and not incremented:
            github_bucket["rate_limit_events_total"] = (
                github_bucket.get("rate_limit_events_total", 0) + 1
            )

    if exc is not None and isinstance(exc, httpx.TimeoutException):
        github_bucket["timeouts_total"] = github_bucket.get("timeouts_total", 0) + 1


def _metrics_snapshot() -> Dict[str, Any]:
    """Return a shallow, JSON-safe snapshot of in-process metrics.

    The metrics registry is intentionally small and numeric, but this helper
    defensively normalizes missing buckets and coerces values to ``int`` where
    possible so that the health payload remains stable even if future fields are
    added.
    """

    tools = _METRICS.get("tools", {})
    github = _METRICS.get("github", {})

    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:  # pragma: no cover - defensive
            return default

    return {
        "tools": tools,
        "github": {
            "requests_total": _as_int(github.get("requests_total", 0)),
            "errors_total": _as_int(github.get("errors_total", 0)),
            "rate_limit_events_total": _as_int(github.get("rate_limit_events_total", 0)),
            "timeouts_total": _as_int(github.get("timeouts_total", 0)),
        },
    }


__all__ = [
    "_metrics_snapshot",
    "_record_github_request",
    "_record_tool_call",
    "_reset_metrics_for_tests",
]
