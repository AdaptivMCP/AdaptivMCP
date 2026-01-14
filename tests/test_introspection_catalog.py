from __future__ import annotations

import types

import asyncio


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

    assert {"list_tools", "list_all_actions", "list_write_actions"}.issubset(names)


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
