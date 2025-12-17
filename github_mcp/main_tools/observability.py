from __future__ import annotations

from typing import Any, Dict

import github_mcp.mcp_server.context as ctx
import github_mcp.server as server
from github_mcp.config import ERROR_LOG_CAPACITY, ERROR_LOG_HANDLER

_LEVELS = {
    "CRITICAL": 50,
    "ERROR": 40,
    "WARNING": 30,
    "INFO": 20,
    "DEBUG": 10,
}


def get_recent_tool_events(limit: int = 50, include_success: bool = True) -> Dict[str, Any]:
    """Return recent tool-call events captured in-memory by the server wrappers."""

    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 50

    events = list(getattr(server, "RECENT_TOOL_EVENTS", []))
    if not include_success:
        events = [e for e in events if e.get("event") != "tool_recent_ok"]

    # newest first
    events = list(reversed(events))

    if limit_int <= 0:
        limit_int = len(events)

    capacity = getattr(server, "RECENT_TOOL_EVENTS_CAPACITY", None)
    if isinstance(capacity, int) and capacity > 0:
        limit_int = max(1, min(capacity, limit_int))
    else:
        limit_int = max(1, limit_int)

    events = events[:limit_int]

    narrative = []
    for e in events:
        msg = e.get("user_message")
        if not msg:
            tool = e.get("tool_name") or "tool"
            ev = e.get("event") or "event"
            repo = e.get("repo") or "-"
            ref = e.get("ref") or "-"
            dur = e.get("duration_ms")
            loc = f"{repo}@{ref}" if ref not in {None, "", "-"} else repo
            if ev == "tool_recent_start":
                msg = f"Starting {tool} on {loc}."
            elif ev == "tool_recent_ok":
                msg = (
                    f"Finished {tool} on {loc}{(' in %sms' % dur) if isinstance(dur, int) else ''}."
                )
            else:
                msg = f"{tool} event {ev} on {loc}."
        narrative.append(msg)

    transcript = "\n".join(narrative)

    total_available = len(list(getattr(server, "RECENT_TOOL_EVENTS", [])))
    total_recorded = getattr(ctx, "RECENT_TOOL_EVENTS_TOTAL", 0)
    if not isinstance(total_recorded, int) or total_recorded < total_available:
        total_recorded = total_available

    return {
        "limit": limit_int,
        "include_success": include_success,
        "events": events,
        "narrative": narrative,
        "transcript": transcript,
        "capacity": None if not (isinstance(capacity, int) and capacity > 0) else capacity,
        "total_recorded": total_recorded,
        "dropped": getattr(ctx, "RECENT_TOOL_EVENTS_DROPPED", 0),
        "total_available": total_available,
    }


def get_recent_server_errors(limit: int = 50) -> Dict[str, Any]:
    """Return recent server-side error logs for failed MCP tool calls."""

    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 50

    records = getattr(ERROR_LOG_HANDLER, "records", [])
    records = list(reversed(records))

    if limit_int <= 0:
        limit_int = len(records)

    if ERROR_LOG_CAPACITY > 0:
        limit_int = max(1, min(ERROR_LOG_CAPACITY, limit_int))
    else:
        limit_int = max(1, limit_int)

    # Include recent server logs as additional context for debugging.
    try:
        from github_mcp.main_tools.server_logs import get_recent_server_logs as _get_logs

        server_logs = _get_logs(limit=max(100, limit_int), min_level="INFO")
    except Exception as e:  # noqa: BLE001
        server_logs = {"error": str(e)}

    return {
        "limit": limit_int,
        "capacity": None if ERROR_LOG_CAPACITY <= 0 else ERROR_LOG_CAPACITY,
        "errors": records[:limit_int],
        "total_available": len(records),
        "server_logs": server_logs,
    }
