from __future__ import annotations

import os
import sys
import contextvars
from collections import deque
from typing import Any, Optional

from github_mcp import http_clients as _http_clients
from github_mcp.http_clients import _github_client_instance
from github_mcp.utils import _env_flag

# Diagnostics toggles
GITHUB_MCP_DIAGNOSTICS = _env_flag('GITHUB_MCP_DIAGNOSTICS', True)
GITHUB_MCP_RECORD_RECENT_EVENTS = _env_flag('GITHUB_MCP_RECORD_RECENT_EVENTS', True)


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


# Per-request context (populated by ASGI middleware).
# These are intentionally best-effort: if missing, tool execution still proceeds.
REQUEST_SESSION_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "github_mcp.request_session_id", default=None
)
REQUEST_MESSAGE_ID: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "github_mcp.request_message_id", default=None
)
REQUEST_PATH: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "github_mcp.request_path", default=None
)
REQUEST_RECEIVED_AT: contextvars.ContextVar[float] = contextvars.ContextVar(
    "github_mcp.request_received_at", default=0.0
)


def get_request_context() -> dict[str, Any]:
    """Return the current best-effort request context for logs/dedupe."""

    return {
        "session_id": REQUEST_SESSION_ID.get(),
        "message_id": REQUEST_MESSAGE_ID.get(),
        "path": REQUEST_PATH.get(),
        "received_at": REQUEST_RECEIVED_AT.get(),
    }


# Recent tool-call events (used by get_recent_tool_events).
#
# Default is intentionally large to avoid losing diagnostics during long
# assistant-driven sessions. Set MCP_RECENT_TOOL_EVENTS_CAPACITY <= 0 to disable
# truncation.
RECENT_TOOL_EVENTS_CAPACITY = _int_env('MCP_RECENT_TOOL_EVENTS_CAPACITY', 5000)

if RECENT_TOOL_EVENTS_CAPACITY <= 0:
    RECENT_TOOL_EVENTS: Any = []  # list of dicts
else:
    RECENT_TOOL_EVENTS = deque(maxlen=max(1, RECENT_TOOL_EVENTS_CAPACITY))

RECENT_TOOL_EVENTS_TOTAL = 0
RECENT_TOOL_EVENTS_DROPPED = 0


def _record_recent_tool_event(event: dict) -> None:
    """Best-effort in-memory event buffer for debugging recent tool calls."""

    if not GITHUB_MCP_RECORD_RECENT_EVENTS:
        return None

    global RECENT_TOOL_EVENTS_TOTAL, RECENT_TOOL_EVENTS_DROPPED
    try:
        RECENT_TOOL_EVENTS_TOTAL += 1
        if isinstance(RECENT_TOOL_EVENTS, deque):
            maxlen = RECENT_TOOL_EVENTS.maxlen
            if maxlen and len(RECENT_TOOL_EVENTS) >= maxlen:
                RECENT_TOOL_EVENTS_DROPPED += 1
        RECENT_TOOL_EVENTS.append(event)
    except Exception:
        # Diagnostics should never crash tool execution.
        pass


WRITE_ALLOWED = _env_flag('GITHUB_MCP_WRITE_ALLOWED', True)
COMPACT_METADATA_DEFAULT = _env_flag('GITHUB_MCP_COMPACT_METADATA', True)
CONTROLLER_REPO = os.environ.get(
    'GITHUB_MCP_CONTROLLER_REPO', 'Proofgate-Revocations/chatgpt-mcp-github'
)
CONTROLLER_DEFAULT_BRANCH = os.environ.get('GITHUB_MCP_CONTROLLER_BRANCH', 'main')

# Canonical args examples shown in tool descriptions to reduce malformed tool calls.
_TOOL_EXAMPLES: dict[str, str] = {
    'run_command': '{"full_name":"owner/repo","ref":"main","command":"pytest"}',
    'ensure_workspace_clone': '{"full_name":"owner/repo","ref":"feature-branch","reset":true}',
    'get_workspace_file_contents': '{"full_name":"owner/repo","ref":"feature-branch","path":"path/to/file.py"}',
    'set_workspace_file_contents': '{\"full_name\":\"owner/repo\",\"ref\":\"feature-branch\",\"path\":\"path/to/file.py\",\"content\":\"...\"}',
    'fetch_files': '{"full_name":"owner/repo","ref":"main","paths":["main.py"]}',
    'open_file_context': '{"full_name":"owner/repo","ref":"main","path":"main.py","start_line":1,"max_lines":200}',
    'update_files_and_open_pr': '{"full_name":"owner/repo","base_branch":"main","new_branch":"feature/my-change","files":[{"path":"README.md","content":"..."}],"title":"My change","body":"Why this change"}',
}

_DISCONNECT_ERROR_NAMES = {
    "ClosedResourceError",
    "BrokenResourceError",
    "EndOfStream",
}


def _build_mcp():
    from fastmcp import FastMCP
    from mcp.shared import session as mcp_shared_session
    from mcp.types import Icon

    mcp_instance = FastMCP(
        name="Adaptiv Controller – GitHub",
        instructions=(
            "Use these tools to browse, edit, and maintain GitHub repositories via the Adaptiv Controller.\n"
            "Prefer readable tool outputs and keep responses concise."
        ),
        version="1.0.0",
        icons=[
            Icon(src="/static/logo/adaptiv-icon-128.png", mimeType="image/png", sizes=["128x128"]),
            Icon(src="/static/logo/adaptiv-icon-256.png", mimeType="image/png", sizes=["256x256"]),
        ],
    )

    _orig_send_response = mcp_shared_session.BaseSession._send_response

    async def _quiet_send_response(self, request_id, response):
        try:
            return await _orig_send_response(self, request_id, response)
        except Exception as exc:
            if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
                return None
            if exc.__class__.__name__ in _DISCONNECT_ERROR_NAMES:
                return None
            raise

    mcp_shared_session.BaseSession._send_response = _quiet_send_response
    return mcp_instance


class _LazyMCP:
    __slots__ = ("_instance",)

    def __init__(self) -> None:
        self._instance = None

    def _get_instance(self):
        if self._instance is None:
            self._instance = _build_mcp()
        return self._instance

    def __getattr__(self, name: str):
        return getattr(self._get_instance(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_instance":
            object.__setattr__(self, name, value)
        else:
            setattr(self._get_instance(), name, value)

    def __repr__(self) -> str:
        return repr(self._get_instance())


mcp = _LazyMCP()


async def _github_request(*args, **kwargs):
    client_factory = getattr(sys.modules.get('main'), '_github_client_instance', None)
    kwargs.setdefault('client_factory', client_factory or _github_client_instance)
    return await _http_clients._github_request(*args, **kwargs)
