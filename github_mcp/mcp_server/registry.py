from __future__ import annotations

from typing import Any, Optional

_REGISTERED_MCP_TOOLS: list[tuple[Any, Any]] = []


def _registered_tool_name(tool: Any, func: Any) -> Optional[str]:
    name = getattr(tool, "name", None)
    if name:
        return str(name)

    name = getattr(func, "__mcp_tool_name__", None)
    if name:
        return str(name)

    name = getattr(func, "__name__", None)
    if name:
        return str(name)

    name = getattr(tool, "__name__", None)
    if name:
        return str(name)

    return None


def _find_registered_tool(tool_name: str) -> Optional[tuple[Any, Any]]:
    for tool, func in _REGISTERED_MCP_TOOLS:
        name = _registered_tool_name(tool, func)
        if name == tool_name:
            return tool, func
    return None
