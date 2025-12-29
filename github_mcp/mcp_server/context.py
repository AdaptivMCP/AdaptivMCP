"""
Request + tool execution context.

Goals:
- Provide the stable public surface expected by github_mcp/server.py.
- Do not implement “guardrails” beyond a single WRITE_ALLOWED switch.
- Keep recent tool-event tracking for observability (non-blocking).
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from contextvars import ContextVar
from typing import Any, Deque, Dict, List, Mapping, Optional

from github_mcp.utils import _env_flag

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
except Exception as exc:
    raise RuntimeError(
        "FastMCP import failed. Ensure the MCP server dependency is installed and importable "
        "(expected: from mcp.server.fastmcp import FastMCP)."
    ) from exc


# -----------------------------------------------------------------------------
# Public MCP server instance used for tool registration
# -----------------------------------------------------------------------------

mcp = FastMCP("github_mcp")


# -----------------------------------------------------------------------------
# Correlation ids (set these in request middleware / entrypoints)
# -----------------------------------------------------------------------------

REQUEST_MESSAGE_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_MESSAGE_ID", default=None)
REQUEST_SESSION_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_SESSION_ID", default=None)


def get_request_context() -> Dict[str, Any]:
    """Small, stable context blob suitable for logs (avoid secrets)."""
    return {
        "message_id": REQUEST_MESSAGE_ID.get(),
        "session_id": REQUEST_SESSION_ID.get(),
        "ts": time.time(),
    }


# -----------------------------------------------------------------------------
# Single write gate (the only blocking switch you keep)
# -----------------------------------------------------------------------------

class _BoolFlag:
    """
    Mutable boolean holder so imports share the same object.
    Use WRITE_ALLOWED.value = True/False.
    """

    __slots__ = ("value",)

    def __init__(self, value: bool) -> None:
        self.value = bool(value)

    def __bool__(self) -> bool:
        return bool(self.value)

    def __repr__(self) -> str:
        return f"_BoolFlag(value={self.value})"


WRITE_ALLOWED = _BoolFlag(_env_flag("WRITE_ALLOWED", False))


def set_write_allowed(value: bool) -> None:
    """Preferred programmatic setter."""
    WRITE_ALLOWED.value = bool(value)


def get_write_allowed() -> bool:
    return bool(WRITE_ALLOWED)


# -----------------------------------------------------------------------------
# Controller defaults (expected by github_mcp/server.py)
# -----------------------------------------------------------------------------

CONTROLLER_REPO = os.getenv("CONTROLLER_REPO", "").strip() or os.getenv("GITHUB_CONTROLLER_REPO", "").strip()
CONTROLLER_DEFAULT_BRANCH = os.getenv("CONTROLLER_DEFAULT_BRANCH", "").strip() or os.getenv(
    "GITHUB_CONTROLLER_DEFAULT_BRANCH", "main"
).strip()

COMPACT_METADATA_DEFAULT = _env_flag("COMPACT_METADATA_DEFAULT", True)


# -----------------------------------------------------------------------------
# Recent tool events (non-blocking telemetry)
# -----------------------------------------------------------------------------

RECENT_TOOL_EVENTS_CAPACITY = int(os.getenv("RECENT_TOOL_EVENTS_CAPACITY", "2000") or "2000")

_RECENT_LOCK = threading.Lock()
RECENT_TOOL_EVENTS: Deque[Dict[str, Any]] = deque(maxlen=max(1, RECENT_TOOL_EVENTS_CAPACITY))

RECENT_TOOL_EVENTS_TOTAL = 0
RECENT_TOOL_EVENTS_DROPPED = 0


def _record_recent_tool_event(event: Mapping[str, Any]) -> None:
    global RECENT_TOOL_EVENTS_TOTAL, RECENT_TOOL_EVENTS_DROPPED

    with _RECENT_LOCK:
        RECENT_TOOL_EVENTS_TOTAL += 1
        before = len(RECENT_TOOL_EVENTS)
        RECENT_TOOL_EVENTS.append(dict(event))
        after = len(RECENT_TOOL_EVENTS)

        # If deque was full, appending discards one from the left (length stays constant).
        if before == after and before == RECENT_TOOL_EVENTS.maxlen:
            RECENT_TOOL_EVENTS_DROPPED += 1


def get_recent_tool_events(limit: int = 100) -> List[Dict[str, Any]]:
    if limit <= 0:
        return []
    with _RECENT_LOCK:
        items = list(RECENT_TOOL_EVENTS)[-limit:]
    items.reverse()
    return items


# -----------------------------------------------------------------------------
# GitHub request helper (expected by github_mcp/server.py)
# -----------------------------------------------------------------------------

# Prefer to re-export the canonical HTTP client helper if it exists.
def _github_request(*args: Any, **kwargs: Any) -> Any:
    """
    Thin re-export wrapper. If your http_clients module exposes _github_request,
    this forwards to it. Otherwise it errors clearly at call time.
    """
    try:
        from github_mcp.http_clients import _github_request as _impl  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "github_mcp.http_clients._github_request is not available but was requested."
        ) from exc
    return _impl(*args, **kwargs)


# -----------------------------------------------------------------------------
# Optional examples map (expected by github_mcp/server.py)
# -----------------------------------------------------------------------------

_TOOL_EXAMPLES: Dict[str, Any] = {}