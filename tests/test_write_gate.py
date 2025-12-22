import pytest

import github_mcp.server as server
from github_mcp.mcp_server import write_gate


@pytest.mark.parametrize("target_ref", [None, "refs/heads/main", "feature/foo"])
def test_write_gate_never_blocks(monkeypatch, target_ref):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    write_gate._ensure_write_allowed("write attempt", target_ref=target_ref)


def test_authorize_write_actions_forces_allowed(monkeypatch):
    from main import authorize_write_actions

    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    result = authorize_write_actions(approved=False)

    assert server.WRITE_ALLOWED is True
    assert result == {"write_allowed": True}
