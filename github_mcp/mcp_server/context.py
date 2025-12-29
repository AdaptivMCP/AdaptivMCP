"""
Request + tool execution context.

This version is intentionally minimal:
- Provides request-scoped ids for correlation (message/session).
- Provides a FastMCP instance (mcp) used by decorators.
- Provides a bounded in-memory recent-event buffer for diagnostics.
- Does NOT implement blocking guardrails beyond what decorators enforce.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from contextvars import ContextVar
from typing import Any, Dict, List, Mapping, Optional

try:
    # Most MCP servers use this import path.
    from mcp.server.fastmcp import FastMCP  # type: ignore
except Exception as exc:
    raise RuntimeError(
        "FastMCP import failed. Ensure the MCP server dependency is installed and importable."
    ) from exc


# Public MCP server instance used for tool registration.
mcp = FastMCP("github_mcp")


# Correlation ids (best-effort). Set these from your HTTP middleware / request entrypoint.
REQUEST_MESSAGE_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_MESSAGE_ID", default=None)
REQUEST_SESSION_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_SESSION_ID", default=None)


# Recent tool events (for debugging/UX; not a guardrail).
_RECENT_LOCK = threading.Lock()
_RECENT_MAX = 2000
_RECENT_EVENTS: deque[Dict[str, Any]] = deque(maxlen=_RECENT_MAX)


def get_request_context() -> Dict[str, Any]:
    """
    Return a small, stable request context blob for logs/events.
    Keep this free of secrets; treat it as diagnostic metadata.
    """
    return {
        "message_id": REQUEST_MESSAGE_ID.get(),
        "session_id": REQUEST_SESSION_ID.get(),
        "ts": time.time(),
    }


def _record_recent_tool_event(event: Mapping[str, Any]) -> None:
    with _RECENT_LOCK:
        _RECENT_EVENTS.append(dict(event))


def get_recent_tool_events(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Convenience helper (optional): returns most recent events, newest-first.
    """
    if limit <= 0:
        return []
    with _RECENT_LOCK:
        items = list(_RECENT_EVENTS)[-limit:]
    items.reverse()
    return items