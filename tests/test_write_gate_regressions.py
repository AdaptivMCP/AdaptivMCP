from __future__ import annotations

import importlib

import pytest

from github_mcp.exceptions import WriteApprovalRequiredError


def _reload_context():
    """Reload github_mcp.mcp_server.context to refresh module state."""
    import github_mcp.mcp_server.context as context

    return importlib.reload(context)


def test_write_gate_follows_auto_approve_env(monkeypatch):
    context = _reload_context()
    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true")
    assert context.get_write_allowed(refresh_after_seconds=0.0) is True
    assert bool(context.WRITE_ALLOWED) is True

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "false")
    assert context.get_write_allowed(refresh_after_seconds=0.0) is False
    assert bool(context.WRITE_ALLOWED) is False


def test_decorators_enforce_auto_approve_gate(monkeypatch):
    _reload_context()

    from github_mcp.mcp_server.decorators import _enforce_write_allowed

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true")
    _enforce_write_allowed("read_tool", write_action=False)
    _enforce_write_allowed("write_tool", write_action=True)

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "false")
    _enforce_write_allowed("read_tool", write_action=False)
    with pytest.raises(WriteApprovalRequiredError) as excinfo:
        _enforce_write_allowed("write_tool", write_action=True)
    assert "Write approval required" in str(excinfo.value)


def test_no_write_gate_env_var_in_ci():
    ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
    assert "ADAPTIV_MCP_WRITE_ALLOWED" not in ci
    # Guard against introducing legacy gates like MCP_WRITE_ALLOWED or WRITE_ALLOWED.
    import re

    assert re.search(r"(^|\s)MCP_WRITE_ALLOWED\s*:", ci, flags=re.MULTILINE) is None
    assert re.search(r"(^|\s)WRITE_ALLOWED\s*:", ci, flags=re.MULTILINE) is None
