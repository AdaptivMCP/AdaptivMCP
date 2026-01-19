from __future__ import annotations

import asyncio
import types

import main
from github_mcp.main_tools import introspection


def _make_tool(name: str, write_action: bool) -> types.SimpleNamespace:
    return types.SimpleNamespace(name=name, write_action=write_action)


def _make_fn(name: str):
    def _fn():
        return "ok"

    _fn.__name__ = name
    return _fn


def test_list_all_actions_includes_introspection_tools():
    catalog = introspection.list_all_actions(include_parameters=False, compact=True)
    names = {tool.get("name") for tool in catalog.get("tools", [])}

    assert {
        "list_resources",
        "list_tools",
        "list_all_actions",
        "list_write_actions",
    }.issubset(names)


def test_list_write_actions_filters_write_action(monkeypatch):
    registry = [
        (_make_tool("read_tool", False), _make_fn("read_tool")),
        (_make_tool("write_tool", True), _make_fn("write_tool")),
    ]
    monkeypatch.setattr(main, "_REGISTERED_MCP_TOOLS", registry)

    result = introspection.list_write_actions(include_parameters=False, compact=True)

    assert [tool["name"] for tool in result["tools"]] == ["write_tool"]
    assert result["tools"][0]["write_action"] is True
    assert result["tools"][0]["write_allowed"] is True


def test_list_tools_filters_and_prefix(monkeypatch):
    registry = [
        (_make_tool("read_tool", False), _make_fn("read_tool")),
        (_make_tool("write_tool", True), _make_fn("write_tool")),
    ]
    monkeypatch.setattr(main, "_REGISTERED_MCP_TOOLS", registry)

    only_write = asyncio.run(introspection.list_tools(only_write=True))
    assert [tool["name"] for tool in only_write["tools"]] == ["write_tool"]
    assert only_write["tools"][0]["write_allowed"] is True

    only_read = asyncio.run(introspection.list_tools(only_read=True))
    assert [tool["name"] for tool in only_read["tools"]] == [
        "list_all_actions",
        "read_tool",
    ]

    prefixed = asyncio.run(introspection.list_tools(name_prefix="read"))
    assert [tool["name"] for tool in prefixed["tools"]] == ["read_tool"]
    assert prefixed["tools"][0]["write_action"] is False
    assert prefixed["tools"][0]["write_allowed"] is True


def test_list_tools_write_allowed_true(monkeypatch):
    registry = [
        (_make_tool("read_tool", False), _make_fn("read_tool")),
        (_make_tool("write_tool", True), _make_fn("write_tool")),
    ]
    monkeypatch.setattr(main, "_REGISTERED_MCP_TOOLS", registry)

    result = asyncio.run(introspection.list_tools())
    idx = {tool["name"]: tool for tool in result["tools"]}

    assert idx["read_tool"]["write_action"] is False
    assert idx["read_tool"]["write_allowed"] is True

    assert idx["write_tool"]["write_action"] is True
    assert idx["write_tool"]["write_allowed"] is True


def test_list_introspection_reports_registry_errors(monkeypatch):
    registry = [
        {"name": "bad_entry"},
        (_make_tool("bad_callable", False), "not_callable"),
        (_make_tool("good_tool", False), _make_fn("good_tool")),
    ]
    monkeypatch.setattr(main, "_REGISTERED_MCP_TOOLS", registry)

    catalog = introspection.list_all_actions(include_parameters=False, compact=True)
    assert "errors" in catalog
    assert any(error.get("entry_index") == 0 for error in catalog["errors"])
    assert any(error.get("entry_index") == 1 for error in catalog["errors"])

    tools = {tool.get("name") for tool in catalog.get("tools", [])}
    assert "good_tool" in tools

    listed = asyncio.run(introspection.list_tools())
    assert "errors" in listed

    resources = introspection.list_resources(base_path="/api")
    assert "errors" in resources
    uris = {resource.get("uri") for resource in resources.get("resources", [])}
    assert "/api/tools/good_tool" in uris


def test_list_write_tools_tracks_registry_and_categories(monkeypatch):
    custom_fn = _make_fn("custom_write_tool")
    custom_fn.__mcp_ui__ = {"group": "workspace"}

    workflow_fn = _make_fn("trigger_workflow_dispatch")
    registry = [
        (_make_tool("custom_write_tool", True), custom_fn),
        (_make_tool("read_tool", False), _make_fn("read_tool")),
        (_make_tool("trigger_workflow_dispatch", True), workflow_fn),
    ]
    monkeypatch.setattr(main, "_REGISTERED_MCP_TOOLS", registry)

    result = introspection.list_write_tools()
    tools_by_name = {tool["name"]: tool for tool in result["tools"]}

    assert "custom_write_tool" in tools_by_name
    assert tools_by_name["custom_write_tool"]["category"] == "workspace"

    assert "trigger_workflow_dispatch" in tools_by_name
    assert tools_by_name["trigger_workflow_dispatch"]["category"] == "workflow"

    assert "read_tool" not in tools_by_name
