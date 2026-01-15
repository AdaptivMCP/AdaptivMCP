from __future__ import annotations

import asyncio
import types

import main

from github_mcp.main_tools import introspection
from github_mcp.mcp_server.registry import _registered_tool_name


def _make_tool(name: str, write_action: bool) -> types.SimpleNamespace:
    return types.SimpleNamespace(name=name, write_action=write_action)


def _make_fn(name: str):
    def _fn():
        return "ok"

    _fn.__name__ = name
    return _fn


def test_list_all_actions_registry_has_no_duplicates_and_callables() -> None:
    """Guardrail: registry tool names should be unique and each entry should have a callable."""

    registered_names: list[str] = []
    for tool_obj, func in main._REGISTERED_MCP_TOOLS:
        assert callable(func), "Registered tool is missing a callable implementation"
        name = _registered_tool_name(tool_obj, func)
        if name:
            registered_names.append(name)

    assert registered_names, "Expected at least one registered tool"
    assert len(registered_names) == len(set(registered_names)), (
        "Duplicate tool names detected in registry"
    )

    catalog = introspection.list_all_actions(include_parameters=False, compact=True)
    catalog_names = [t.get("name") for t in catalog.get("tools", [])]
    assert len(catalog_names) == len(set(catalog_names)), "Duplicate tool names in list_all_actions"

    # Every registered tool must appear in the catalog.
    missing = sorted(set(registered_names) - set(catalog_names))
    assert not missing, f"Registered tools missing from list_all_actions: {missing}"

    # Every catalog tool (except the synthetic fallback) must have a callable in the registry.
    registry_map: dict[str, object] = {}
    for tool_obj, func in main._REGISTERED_MCP_TOOLS:
        name = _registered_tool_name(tool_obj, func)
        if name and name not in registry_map:
            registry_map[name] = func

    for name in catalog_names:
        if name == "list_all_actions":
            continue
        assert name in registry_map, f"Catalog tool has no registered callable: {name}"
        assert callable(registry_map[name]), f"Catalog tool callable is not callable: {name}"


def test_describe_tool_dedupes_requested_names_and_round_trips() -> None:
    catalog = introspection.list_all_actions(include_parameters=False, compact=True)
    names = [t["name"] for t in catalog.get("tools", [])]
    # Pick a deterministic, small sample.
    sample = names[:3]
    assert sample, "Expected at least one tool in catalog"

    requested = [sample[0], sample[0], sample[-1]]
    described = asyncio.run(introspection.describe_tool(names=requested, include_parameters=True))

    described_names = [t.get("name") for t in described.get("tools", [])]
    assert described_names == [sample[0], sample[-1]]

    for tool in described.get("tools", []) or []:
        assert "input_schema" in tool, (
            "describe_tool(include_parameters=True) should return input_schema"
        )


def test_list_all_actions_deduplicates_duplicate_registry_entries(monkeypatch) -> None:
    registry = [
        (_make_tool("dup_tool", False), _make_fn("dup_tool")),
        (_make_tool("dup_tool", False), _make_fn("dup_tool_alt")),
        (_make_tool("other_tool", False), _make_fn("other_tool")),
    ]
    monkeypatch.setattr(main, "_REGISTERED_MCP_TOOLS", registry)

    catalog = introspection.list_all_actions(include_parameters=False, compact=True)
    names = [t["name"] for t in catalog.get("tools", [])]

    assert names.count("dup_tool") == 1
    assert "other_tool" in names
