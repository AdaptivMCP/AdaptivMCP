from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest


def _tool_entries():
    """Return the effective tool registry entries that list_all_actions exposes."""

    from github_mcp.main_tools.introspection import (
        _iter_tool_registry,
        list_all_actions,
        list_resources,
        list_tools,
        list_write_actions,
        list_write_tools,
    )

    entries, errors = _iter_tool_registry()
    assert not errors, f"tool registry errors: {errors}"

    forced_entries = [
        (SimpleNamespace(name="list_all_actions", write_action=False), list_all_actions),
        (SimpleNamespace(name="list_tools", write_action=False), list_tools),
        (SimpleNamespace(name="list_resources", write_action=False), list_resources),
        (SimpleNamespace(name="list_write_actions", write_action=False), list_write_actions),
        (SimpleNamespace(name="list_write_tools", write_action=False), list_write_tools),
    ]

    # list_all_actions de-duplicates by tool name, keeping the *first* occurrence.
    # Mirror that behavior here so contract tests compare the same effective
    # callable that powers the published schema registry.
    from github_mcp.mcp_server.registry import _registered_tool_name

    out: list[tuple[object, object]] = []
    seen: set[str] = set()
    for tool_obj, func in forced_entries + list(entries):
        name = _registered_tool_name(tool_obj, func)
        if not isinstance(name, str) or not name:
            continue
        if name in seen:
            continue
        seen.add(name)
        out.append((tool_obj, func))
    return out


def test_list_all_actions_schema_registry_is_self_consistent() -> None:
    """Contract test: published schemas match live callable schema generation."""

    from github_mcp.main_tools.introspection import list_all_actions
    from github_mcp.mcp_server.registry import _registered_tool_name
    from github_mcp.mcp_server.schemas import _schema_for_callable

    catalog = list_all_actions(include_parameters=True, compact=True)
    errors = catalog.get("errors")
    assert not errors, f"list_all_actions returned registry errors: {errors}"

    tools = catalog.get("tools") or []
    assert isinstance(tools, list) and tools, "expected non-empty tool catalog"

    by_name: dict[str, dict] = {}
    for entry in tools:
        assert isinstance(entry, dict)
        name = entry.get("name")
        assert isinstance(name, str) and name
        schema = entry.get("input_schema")
        assert isinstance(schema, dict), f"missing input_schema for {name}"
        # Compatibility field should mirror.
        assert entry.get("inputSchema") == schema
        by_name[name] = schema

    # Verify the public schema registry is derived from the same live callables.
    for tool_obj, func in _tool_entries():
        name = _registered_tool_name(tool_obj, func)
        assert isinstance(name, str) and name
        assert name in by_name, f"tool {name} missing from catalog"
        expected = _schema_for_callable(func, tool_obj, tool_name=name)
        assert by_name[name] == expected, f"schema mismatch for {name}"


def test_schema_generation_from_signatures_does_not_throw() -> None:
    """Contract test: every tool signature must be representable as a schema.

    If this fails, downstream clients (and LLM tool callers) can see stale or
    partial schemas, which tends to cause incorrect invocations.
    """

    from github_mcp.mcp_server.registry import _registered_tool_name
    from github_mcp.mcp_server.schemas import _schema_from_signature

    failures: list[str] = []
    for tool_obj, func in _tool_entries():
        name = _registered_tool_name(tool_obj, func) or "<unknown>"
        try:
            sig = inspect.signature(func)
            schema = _schema_from_signature(sig, tool_name=str(name))
            assert isinstance(schema, dict)
            assert schema.get("type") == "object"
            assert isinstance(schema.get("properties"), dict)
        except Exception as exc:  # pragma: no cover
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    assert not failures, "\n".join(["schema generation failures:"] + failures)


@pytest.mark.parametrize(
    "tool_name",
    [
        "apply_workspace_operations",
        "workspace_apply_ops_and_open_pr",
        "workspace_task_apply_edits",
        "workspace_task_execute",
    ],
)
def test_operation_tools_expose_ops_alias_in_input_schema(tool_name: str) -> None:
    """LLM ergonomics: ops alias must be visible in the tool schema."""

    from github_mcp.main_tools.introspection import list_all_actions

    catalog = list_all_actions(include_parameters=True, compact=True)
    tools = catalog.get("tools") or []
    schema: dict | None = None
    for entry in tools:
        if entry.get("name") == tool_name:
            schema = entry.get("input_schema")
            break

    if schema is None:
        pytest.skip(f"tool not registered in catalog: {tool_name}")
    assert isinstance(schema, dict)
    props = schema.get("properties") or {}
    assert isinstance(props, dict)
    assert "operations" in props, f"{tool_name} missing 'operations' in schema"
    assert "ops" in props, f"{tool_name} missing 'ops' alias in schema"

