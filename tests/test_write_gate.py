import pytest

import github_mcp.server as server
from github_mcp.exceptions import WriteNotAuthorizedError
from github_mcp.mcp_server import write_gate


@pytest.mark.parametrize("target_ref", [None, "refs/heads/main", "feature/foo"])
def test_unapproved_writes_always_blocked(monkeypatch, target_ref):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    with pytest.raises(WriteNotAuthorizedError):
        write_gate._ensure_write_allowed("write attempt", target_ref=target_ref)


def test_approved_writes_allowed(monkeypatch):
    monkeypatch.setattr(server, "WRITE_ALLOWED", True)

    write_gate._ensure_write_allowed("write attempt", target_ref="refs/heads/main")
