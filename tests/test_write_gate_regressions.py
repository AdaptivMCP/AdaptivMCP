from __future__ import annotations

import importlib

import pytest
from github_mcp.mcp_server.registry import _registered_tool_name


def _reload_context():
    """Reload github_mcp.mcp_server.context to refresh module state."""
    import github_mcp.mcp_server.context as context

    return importlib.reload(context)


def test_write_gate_always_allows_writes(monkeypatch):
    context = _reload_context()
    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true")
    assert context.get_write_allowed(refresh_after_seconds=0.0) is True
    assert bool(context.WRITE_ALLOWED) is True

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "false")
    assert context.get_write_allowed(refresh_after_seconds=0.0) is True
    assert bool(context.WRITE_ALLOWED) is True


def test_decorators_no_longer_enforce_auto_approve_gate(monkeypatch):
    _reload_context()

    from github_mcp.mcp_server.decorators import _enforce_write_allowed

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true")
    _enforce_write_allowed("read_tool", write_action=False)
    _enforce_write_allowed("write_tool", write_action=True)

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "false")
    _enforce_write_allowed("read_tool", write_action=False)
    _enforce_write_allowed("write_tool", write_action=True)


def test_no_write_gate_env_var_in_ci():
    # Some distributions of this repo (for example, minimal release bundles)
    # may omit GitHub workflow files. Skip gracefully when absent.
    import os

    if not os.path.exists(".github/workflows/ci.yml"):
        pytest.skip("CI workflow file not present in this checkout")

    ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
    assert "ADAPTIV_MCP_WRITE_ALLOWED" not in ci
    # Guard against introducing legacy gates like MCP_WRITE_ALLOWED or WRITE_ALLOWED.
    import re

    assert re.search(r"(^|\s)MCP_WRITE_ALLOWED\s*:", ci, flags=re.MULTILINE) is None
    assert re.search(r"(^|\s)WRITE_ALLOWED\s*:", ci, flags=re.MULTILINE) is None


def _pick_registered_write_tool():
    import main

    for tool_obj, func in getattr(main, "_REGISTERED_MCP_TOOLS", []):
        if getattr(func, "__mcp_write_action__", False):
            return tool_obj, func
    pytest.skip("No registered write tools found to validate write gate metadata.")


def test_write_gate_metadata_refreshes_when_auto_approve_changes(monkeypatch):
    context = _reload_context()
    tool_obj, func = _pick_registered_write_tool()
    tool_name = _registered_tool_name(tool_obj, func) or getattr(
        tool_obj, "name", "unknown"
    )

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "false")
    assert context.get_auto_approve_enabled() is True
    doc = func.__doc__ or ""
    assert "write_allowed: true" in doc, (
        f"{tool_name} docstring not updated for always-on write access"
    )
    description = getattr(tool_obj, "description", "") or ""
    assert "write_allowed: true" in description

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true")
    assert context.get_auto_approve_enabled() is True
    doc = func.__doc__ or ""
    assert "write_allowed: true" in doc, (
        f"{tool_name} docstring not updated for gate on"
    )
    description = getattr(tool_obj, "description", "") or ""
    assert "write_allowed: true" in description


def test_auto_approve_env_not_overridden_by_manual_write_allowed(monkeypatch):
    context = _reload_context()
    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true")
    assert context.get_auto_approve_enabled() is True

    context.set_write_allowed(False)
    assert context.get_auto_approve_enabled() is True
    assert bool(context.WRITE_ALLOWED) is True
