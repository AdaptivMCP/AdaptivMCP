import pytest

import main  # noqa: F401
from github_mcp import server


def _registered_names() -> set[str]:
    return {tool.name for tool, _func in server._REGISTERED_MCP_TOOLS}


def test_list_all_actions_is_registered():
    assert "list_all_actions" in _registered_names()


@pytest.mark.asyncio
async def test_registered_tools_match_fastmcp_registry():
    tools = await server.mcp.get_tools()

    if isinstance(tools, dict):
        mcp_names = set(tools.keys())
    else:
        mcp_names = {getattr(t, "name", str(t)) for t in tools}

    reg_names = _registered_names()

    assert mcp_names == reg_names
