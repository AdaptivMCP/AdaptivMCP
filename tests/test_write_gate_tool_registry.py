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
        monkeypatch.delenv("ADAPTIV_MCP_AUTO_APPROVE", raising=False)
    else:
        monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true" if enabled else "false")


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


def test_tools_with_write_action_resolver_are_always_write_gated(monkeypatch):
    """Tools with dynamic write classification must always be gated.

    Contract:
    - Any tool that supplies a write_action_resolver must be registered via the
      mcp_tool wrapper (so wrapper metadata exists).
    - Base write_action must be True so the server treats the tool as
      write-capable and requires approval when auto-approve is disabled.
    """

    resolver_tool_names: list[str] = []

    for tool_obj, func in getattr(main, "_REGISTERED_MCP_TOOLS", []):
        name = _registered_tool_name(tool_obj, func)
        if not name:
            continue
        resolver = getattr(func, "__mcp_write_action_resolver__", None)
        if not callable(resolver):
            continue

        # Wrapper metadata must exist.
        assert hasattr(func, "__mcp_tool__"), f"{name} missing __mcp_tool__ wrapper metadata"
        assert hasattr(func, "__mcp_input_schema__"), f"{name} missing __mcp_input_schema__"
        assert hasattr(func, "__mcp_input_schema_hash__"), (
            f"{name} missing __mcp_input_schema_hash__"
        )
        assert hasattr(func, "__mcp_visibility__"), f"{name} missing __mcp_visibility__"

        # Dynamic tools must be conservatively classified as write-capable.
        assert bool(getattr(func, "__mcp_write_action__", False)) is True, (
            f"{name} has write_action_resolver but base __mcp_write_action__ is not True"
        )

        resolver_tool_names.append(str(name))

    assert resolver_tool_names, "Expected at least one registered tool with write_action_resolver"

    # Auto-approve enabled: no approval required.
    _set_auto_approve(monkeypatch, True)
    catalog = introspection.list_all_actions(include_parameters=True, compact=False)
    idx = {str(t.get("name")): t for t in (catalog.get("tools", []) or []) if t.get("name")}
    for name in resolver_tool_names:
        entry = idx.get(name)
        assert entry is not None, f"Catalog missing resolver tool: {name}"
        assert entry.get("write_auto_approved") is True
        assert entry.get("approval_required") is False
        assert entry.get("write_allowed") is True
        assert entry.get("write_enabled") is True
        assert entry.get("write_actions_enabled") is True

    # Auto-approve disabled: approval required for write-capable tools.
    _set_auto_approve(monkeypatch, False)
    catalog = introspection.list_all_actions(include_parameters=True, compact=False)
    idx = {str(t.get("name")): t for t in (catalog.get("tools", []) or []) if t.get("name")}
    for name in resolver_tool_names:
        entry = idx.get(name)
        assert entry is not None, f"Catalog missing resolver tool: {name}"
        assert entry.get("write_auto_approved") is False
        assert entry.get("approval_required") is True
