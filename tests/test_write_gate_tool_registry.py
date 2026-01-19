from __future__ import annotations

import datetime
import typing
from typing import NotRequired

if not hasattr(typing, "NotRequired"):
    typing.NotRequired = NotRequired

if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.UTC

import main
from github_mcp.main_tools import introspection
from github_mcp.mcp_server.registry import _registered_tool_name


def _set_auto_approve(monkeypatch, enabled: bool | None) -> None:
    if enabled is None:
        monkeypatch.delenv("GITHUB_MCP_AUTO_APPROVE", raising=False)
    else:
        monkeypatch.setenv("GITHUB_MCP_AUTO_APPROVE", "true" if enabled else "false")


def test_every_registered_tool_reports_write_gate_metadata(monkeypatch):
    """Ensure each registered tool surfaces write gate metadata via introspection."""

    _set_auto_approve(monkeypatch, True)
    catalog = introspection.list_all_actions(include_parameters=True, compact=False)
    tools = catalog.get("tools", []) or []
    idx = {str(t.get("name")): t for t in tools if t.get("name")}

    missing = []
    mismatched = []

    for tool_obj, func in getattr(main, "_REGISTERED_MCP_TOOLS", []):
        name = _registered_tool_name(tool_obj, func)
        if not name:
            continue
        name_str = str(name)
        entry = idx.get(name_str)
        if entry is None:
            missing.append(name_str)
            continue

        expected_write_action = bool(getattr(func, "__mcp_write_action__", False))
        if entry.get("write_action") is not expected_write_action:
            mismatched.append(name_str)
            continue

        assert entry.get("write_allowed") is True
        assert entry.get("write_enabled") is True
        assert entry.get("write_auto_approved") is True
        assert entry.get("write_actions_enabled") is True
        assert entry.get("approval_required") is False

    assert not missing, f"Catalog missing registered tools: {sorted(missing)}"
    assert not mismatched, f"Catalog write_action mismatch for tools: {sorted(mismatched)}"

    _set_auto_approve(monkeypatch, False)
    catalog = introspection.list_all_actions(include_parameters=True, compact=False)
    tools = catalog.get("tools", []) or []
    idx = {str(t.get("name")): t for t in tools if t.get("name")}

    for tool_obj, func in getattr(main, "_REGISTERED_MCP_TOOLS", []):
        name = _registered_tool_name(tool_obj, func)
        if not name:
            continue
        entry = idx.get(str(name))
        if entry is None:
            continue
        assert entry.get("write_auto_approved") is False
        if bool(entry.get("write_action")):
            assert entry.get("approval_required") is True
        else:
            assert entry.get("approval_required") is False
