import pytest

import github_mcp.server as server
from github_mcp.exceptions import WriteApprovalRequiredError
from github_mcp.mcp_server import errors, write_gate


def test_soft_write_allowed_when_enabled(monkeypatch):
    monkeypatch.setattr(server, "WRITE_ALLOWED", True)

    write_gate._ensure_write_allowed("soft write", write_kind="soft_write")


def test_hard_write_allowed_when_enabled(monkeypatch):
    monkeypatch.setattr(server, "WRITE_ALLOWED", True)

    write_gate._ensure_write_allowed("hard write", write_kind="hard_write")


def test_write_gate_allows_explicit_approval_when_disabled(monkeypatch):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    write_gate._ensure_write_allowed("approved soft", write_kind="soft_write", approved=True)
    write_gate._ensure_write_allowed("approved hard", write_kind="hard_write", approved=True)


@pytest.mark.parametrize("write_kind", ["soft_write", "hard_write"])
@pytest.mark.parametrize("target_ref", [None, "refs/heads/main", "feature/foo"])
def test_write_gate_blocks_without_approval(monkeypatch, write_kind, target_ref):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    with pytest.raises(WriteApprovalRequiredError) as excinfo:
        write_gate._ensure_write_allowed(
            "write attempt",
            target_ref=target_ref,
            write_kind=write_kind,
        )

    gate = getattr(excinfo.value, "write_gate")
    assert gate["write_kind"] == write_kind
    assert gate["target_ref"] == target_ref
    assert gate["approval_required"] is True


def test_write_gate_structured_error(monkeypatch):
    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    with pytest.raises(WriteApprovalRequiredError) as excinfo:
        write_gate._ensure_write_allowed("blocked operation", write_kind="soft_write")

    payload = errors._structured_tool_error(excinfo.value, context="write_gate_test")

    assert payload["error"]["write_gate"]["write_kind"] == "soft_write"
    assert payload["error"]["approval_required"] is True


def test_authorize_write_actions_toggle(monkeypatch):
    from main import authorize_write_actions

    monkeypatch.setattr(server, "WRITE_ALLOWED", False)

    result = authorize_write_actions(approved=True)

    assert server.WRITE_ALLOWED is True
    assert result == {"write_allowed": True}

    result = authorize_write_actions(approved=False)
    assert server.WRITE_ALLOWED is False
    assert result == {"write_allowed": False}