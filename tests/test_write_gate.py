import importlib

import pytest

import github_mcp.server as server
from github_mcp.mcp_server import write_gate
from github_mcp.exceptions import WriteNotAuthorizedError


@pytest.mark.parametrize("target_ref", [None, "refs/heads/main"])
def test_unapproved_writes_blocked_on_default_branch(monkeypatch, target_ref):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)
    monkeypatch.setattr(server, "CONTROLLER_DEFAULT_BRANCH", "main")

    with pytest.raises(WriteNotAuthorizedError):
        write_gate._ensure_write_allowed("write to default", target_ref=target_ref)


@pytest.mark.parametrize("target_ref", ["feature/foo", "refs/heads/feature/foo"])
def test_non_default_branches_allowed_even_when_gate_disabled(monkeypatch, target_ref):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)
    monkeypatch.setattr(server, "CONTROLLER_DEFAULT_BRANCH", "main")

    # Should not raise because non-default branches are allowed without prior approval.
    write_gate._ensure_write_allowed("write to feature", target_ref=target_ref)


def test_auto_approve_allows_unscoped_write_actions(monkeypatch):
    monkeypatch.setattr(server, "WRITE_ALLOWED", True)

    # No specific ref provided; global approval should allow the write.
    write_gate._ensure_write_allowed("unscoped write")
