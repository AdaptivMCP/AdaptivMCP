from __future__ import annotations

import os
import sys
from collections import deque
from typing import Any

from anyio import ClosedResourceError
from fastmcp import FastMCP
from mcp.types import Icon

from github_mcp import http_clients as _http_clients
from github_mcp.http_clients import _github_client_instance
from github_mcp.redaction import redact_structured
from github_mcp.utils import _env_flag


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


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

    global RECENT_TOOL_EVENTS_TOTAL, RECENT_TOOL_EVENTS_DROPPED
    try:
        event = redact_structured(event)
        RECENT_TOOL_EVENTS_TOTAL += 1
        if isinstance(RECENT_TOOL_EVENTS, deque):
            maxlen = RECENT_TOOL_EVENTS.maxlen
            if maxlen and len(RECENT_TOOL_EVENTS) >= maxlen:
                RECENT_TOOL_EVENTS_DROPPED += 1
        RECENT_TOOL_EVENTS.append(event)
    except Exception:
        # Diagnostics should never crash tool execution.
        pass


WRITE_ALLOWED = _env_flag('GITHUB_MCP_AUTO_APPROVE', False)
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

mcp = FastMCP(
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

# Suppress noisy tracebacks when SSE clients disconnect mid-response.
from mcp.shared import session as mcp_shared_session  # noqa: E402

_orig_send_response = mcp_shared_session.BaseSession._send_response


async def _quiet_send_response(self, request_id, response):
    try:
        return await _orig_send_response(self, request_id, response)
    except ClosedResourceError:
        return None


mcp_shared_session.BaseSession._send_response = _quiet_send_response


async def _github_request(*args, **kwargs):
    client_factory = getattr(sys.modules.get('main'), '_github_client_instance', None)
    kwargs.setdefault('client_factory', client_factory or _github_client_instance)
    return await _http_clients._github_request(*args, **kwargs)
