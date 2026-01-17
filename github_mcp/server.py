"""Public server surface for the GitHub MCP (developer-facing).

This module is the stable import surface for embedding or extending the MCP
server. Most implementation details live under `github_mcp.mcp_server.*`.

For tool authors:
- Use `@mcp_tool(write_action=...)` to register tools with generated input
  schemas and structured error payloads.
- Prefer short, imperative first-line docstrings; the server expands them into
  a full developer reference (parameters, errors, write semantics).
"""

from __future__ import annotations

from github_mcp.http_clients import _github_request  # noqa: F401
from github_mcp.mcp_server.context import (  # noqa: F401
    _TOOL_EXAMPLES,
    COMPACT_METADATA_DEFAULT,
    WRITE_ALLOWED,
    mcp,
)
from github_mcp.mcp_server.decorators import mcp_tool, register_extra_tools_if_available
from github_mcp.mcp_server.errors import _structured_tool_error
from github_mcp.mcp_server.registry import (
    _REGISTERED_MCP_TOOLS,
    _find_registered_tool,
)  # noqa: F401
from github_mcp.mcp_server.schemas import (  # noqa: F401
    _normalize_input_schema,
    _normalize_tool_description,
    _preflight_tool_args,
    _stringify_annotation,
)
from github_mcp.utils import CONTROLLER_DEFAULT_BRANCH, CONTROLLER_REPO, _env_flag  # noqa: F401

__all__ = [
    "COMPACT_METADATA_DEFAULT",
    "CONTROLLER_DEFAULT_BRANCH",
    "CONTROLLER_REPO",
    "WRITE_ALLOWED",
    "_TOOL_EXAMPLES",
    "_REGISTERED_MCP_TOOLS",
    "_find_registered_tool",
    "_github_request",
    "_normalize_input_schema",
    "_structured_tool_error",
    "mcp",
    "mcp_tool",
    "register_extra_tools_if_available",
]
