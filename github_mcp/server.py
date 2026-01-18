"""Public server surface for the GitHub MCP (developer-facing).

This module is the stable import surface for embedding or extending the MCP
server. Most implementation details live under `github_mcp.mcp_server.*`.

Tool authorship notes:

- Tool registration occurs via `@mcp_tool(write_action=...)`, which binds a
  Python callable into the registry with a generated input schema and
  structured error payloads.
- Tool docstrings act as the primary human-readable description. The first
  line is treated as a short summary and is expanded into a reference view
  that includes parameters, errors, and write semantics.
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
from github_mcp.mcp_server.error_handling import _structured_tool_error
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
