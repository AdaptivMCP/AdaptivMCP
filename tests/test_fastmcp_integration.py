"""Exercise registration and a read-only call against the installed FastMCP."""

from __future__ import annotations

import pytest
from fastmcp import Client

import main


@pytest.mark.asyncio
async def test_installed_fastmcp_lists_and_calls_registered_tools() -> None:
    async with Client(main.server.mcp) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert {"list_tools", "terminal_command", "workspace_git_push"} <= names
        result = await client.call_tool("list_tools", {})
        assert not result.is_error
