from __future__ import annotations

import os
import sys
from collections import deque

from anyio import ClosedResourceError
from fastmcp import FastMCP

from github_mcp import http_clients as _http_clients
from github_mcp.http_clients import _github_client_instance
from github_mcp.utils import _env_flag

RECENT_TOOL_EVENTS = deque(maxlen=200)


def _record_recent_tool_event(event: dict) -> None:
    """Best-effort in-memory ring buffer for debugging recent tool calls."""
    try:
        RECENT_TOOL_EVENTS.append(event)
    except Exception:
        pass


WRITE_ALLOWED = _env_flag("GITHUB_MCP_AUTO_APPROVE", False)
COMPACT_METADATA_DEFAULT = _env_flag("GITHUB_MCP_COMPACT_METADATA", True)
CONTROLLER_REPO = os.environ.get(
    "GITHUB_MCP_CONTROLLER_REPO", "Proofgate-Revocations/chatgpt-mcp-github"
)
CONTROLLER_DEFAULT_BRANCH = os.environ.get("GITHUB_MCP_CONTROLLER_BRANCH", "main")

# Canonical args examples shown in tool descriptions to reduce malformed tool calls.
_TOOL_EXAMPLES: dict[str, str] = {
    "run_command": '{"full_name":"owner/repo","ref":"main","command":"pytest"}',
    "ensure_workspace_clone": '{"full_name":"owner/repo","ref":"feature-branch","reset":true}',
    "get_workspace_file_contents": '{"full_name":"owner/repo","ref":"feature-branch","path":"path/to/file.py"}',
    "set_workspace_file_contents": '{\"full_name\":\"owner/repo\",\"ref\":\"feature-branch\",\"path\":\"path/to/file.py\",\"content\":\"...\"}',
    "fetch_files": '{"full_name":"owner/repo","ref":"main","paths":["main.py"]}',
    "open_file_context": '{"full_name":"owner/repo","ref":"main","path":"main.py","start_line":1,"max_lines":200}',
    "update_files_and_open_pr": '{"full_name":"owner/repo","base_branch":"main","new_branch":"feature/my-change","files":[{"path":"README.md","content":"..."}],"title":"My change","body":"Why this change"}',
}

mcp = FastMCP("GitHub Fast MCP")

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
    client_factory = getattr(sys.modules.get("main"), "_github_client_instance", None)
    kwargs.setdefault("client_factory", client_factory or _github_client_instance)
    return await _http_clients._github_request(*args, **kwargs)

