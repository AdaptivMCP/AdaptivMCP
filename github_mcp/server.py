"""Shared server setup and decorator utilities for the GitHub MCP.

This module is the stable public import surface.
Implementation lives under `github_mcp.mcp_server.*`.
"""

from __future__ import annotations

from github_mcp.mcp_server.context import (  # noqa: F401
    _TOOL_EXAMPLES,
    COMPACT_METADATA_DEFAULT,
    CONTROLLER_DEFAULT_BRANCH,
    CONTROLLER_REPO,
    RECENT_TOOL_EVENTS,
    RECENT_TOOL_EVENTS_CAPACITY,
    RECENT_TOOL_EVENTS_DROPPED,
    RECENT_TOOL_EVENTS_TOTAL,
    WRITE_ALLOWED,
    _github_request,
    _record_recent_tool_event,
    mcp,
)
from github_mcp.mcp_server.decorators import mcp_tool, register_extra_tools_if_available
from github_mcp.mcp_server.errors import _structured_tool_error
from github_mcp.mcp_server.registry import (  # noqa: F401
    _REGISTERED_MCP_TOOLS,
    _find_registered_tool,
)
from github_mcp.mcp_server.schemas import (  # noqa: F401
    _format_tool_args_preview,
    _normalize_input_schema,
    _normalize_tool_description,
    _preflight_tool_args,
    _stringify_annotation,
)
from github_mcp.mcp_server.write_gate import _ensure_write_allowed
from github_mcp.utils import _env_flag  # noqa: F401

__all__ = [
    "COMPACT_METADATA_DEFAULT",
    "CONTROLLER_DEFAULT_BRANCH",
    "CONTROLLER_REPO",
    "WRITE_ALLOWED",
    "RECENT_TOOL_EVENTS",
    "RECENT_TOOL_EVENTS_CAPACITY",
    "RECENT_TOOL_EVENTS_TOTAL",
    "RECENT_TOOL_EVENTS_DROPPED",
    "_TOOL_EXAMPLES",
    "_REGISTERED_MCP_TOOLS",
    "_find_registered_tool",
    "_github_request",
    "_normalize_input_schema",
    "_structured_tool_error",
    "_ensure_write_allowed",
    "mcp",
    "mcp_tool",
    "register_extra_tools_if_available",
]
