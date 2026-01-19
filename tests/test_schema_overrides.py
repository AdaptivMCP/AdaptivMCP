from __future__ import annotations

import inspect

from github_mcp.mcp_server.schemas import _normalize_input_schema, _schema_from_signature
from github_mcp.server import _REGISTERED_MCP_TOOLS
from github_mcp.workspace_tools import listing as workspace_listing


def _required_set(schema: dict[str, object] | None) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    required = schema.get("required")
    if not isinstance(required, list):
        return set()
    return {name for name in required if isinstance(name, str)}


def test_search_workspace_signature_schema_requires_query() -> None:
    schema = _schema_from_signature(
        inspect.signature(workspace_listing.search_workspace), tool_name="search_workspace"
    )
    assert "query" in _required_set(schema)


def test_search_workspace_tool_schema_requires_query() -> None:
    tool_obj = None
    func = None
    for candidate_tool, candidate_func in _REGISTERED_MCP_TOOLS:
        name = getattr(candidate_tool, "name", None) or getattr(candidate_func, "__name__", None)
        if name == "search_workspace":
            tool_obj = candidate_tool
            func = candidate_func
            break

    assert tool_obj is not None
    assert func is not None
    assert "query" in _required_set(getattr(func, "__mcp_input_schema__", None))
    assert "query" in _required_set(_normalize_input_schema(tool_obj))
