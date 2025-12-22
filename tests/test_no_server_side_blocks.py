import pytest

import github_mcp.server as server
from github_mcp.http_routes.actions_compat import serialize_actions_for_compatibility
from github_mcp.main_tools.server_config import get_server_config


@pytest.mark.asyncio
async def test_server_config_always_allows_writes(monkeypatch):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    cfg = await get_server_config()

    assert cfg["write_allowed"] is True
    assert "removed" in cfg["approval_policy"]["notes"].lower()


def test_actions_listing_retains_tools(monkeypatch):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    actions = serialize_actions_for_compatibility(server)

    assert actions, "Tool list should still be populated when write gating is disabled."
