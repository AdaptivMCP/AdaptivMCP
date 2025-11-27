from __future__ import annotations

from typing import Any, Callable, Protocol


class ToolDecorator(Protocol):
    """Protocol describing the `mcp_tool` decorator from `main.py`.

    This stays intentionally minimal so that changes to the real decorator
    signature are less likely to break this extension surface.
    """

    def __call__(
        self,
        *,
        write_action: bool = False,
        **tool_kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        ...


def register_extra_tools(mcp_tool: ToolDecorator) -> None:
    """Register optional extra tools on top of the core MCP toolset.

    This function is discovered dynamically by `main.py` (if present) and
    receives the `mcp_tool` decorator so you can define additional tools
    without having to modify the core server implementation.
    """

    @mcp_tool(
        write_action=False,
        description="Ping the MCP server extensions surface. Useful for diagnostics.",
        tags=["meta", "diagnostics"],
    )
    def ping_extensions() -> str:
        return "pong from extra_tools.py"
