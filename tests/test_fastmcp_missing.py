import pytest

from github_mcp.mcp_server import context


def test_missing_fastmcp_raises_on_tool_registration():
    if context.FASTMCP_AVAILABLE:
        pytest.skip("FastMCP installed; missing dependency behavior not applicable.")

    def _tool() -> str:
        return "ok"

    with pytest.raises(RuntimeError, match="FastMCP import failed"):
        context.mcp.tool(
            _tool,
            name="missing_fastmcp_tool",
            description="missing fastmcp tool registration",
            tags=set(),
            meta={},
            annotations={},
        )
