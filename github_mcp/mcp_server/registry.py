from __future__ import annotations

from typing import Any, Optional

_REGISTERED_MCP_TOOLS: list[tuple[Any, Any]] = []


def _find_registered_tool(tool_name: str) -> Optional[tuple[Any, Any]]:
    for tool, func in _REGISTERED_MCP_TOOLS:
        name = getattr(tool, "name", None) or getattr(func, "__name__", None)
        if name == tool_name:
            return tool, func
    return None
