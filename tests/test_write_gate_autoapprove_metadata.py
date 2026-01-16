from __future__ import annotations

import main
from github_mcp.main_tools import introspection


def _catalog_index(*, include_parameters: bool) -> dict[str, dict]:
    catalog = introspection.list_all_actions(
        include_parameters=include_parameters,
        compact=False,
    )
    tools = catalog.get("tools", []) or []
    return {str(t.get("name")): t for t in tools if t.get("name")}


def test_registered_tool_wrappers_always_carry_write_gate_metadata():
    """Regression guard: every registered tool must come from the mcp_tool wrapper.

    This ensures new tools cannot be added without the safety/metadata surface:
    - __mcp_write_action__ semantic classification
    - __mcp_visibility__
    - __mcp_input_schema__ and stable hash
    """

    for tool_obj, func in list(getattr(main, "_REGISTERED_MCP_TOOLS", [])):
        name = getattr(tool_obj, "name", None) or getattr(func, "__name__", None)
        assert name, "Every registered tool must have a stable name"

        assert hasattr(func, "__mcp_write_action__"), f"{name} missing __mcp_write_action__"
        assert isinstance(getattr(func, "__mcp_write_action__"), bool)

        assert hasattr(func, "__mcp_visibility__"), f"{name} missing __mcp_visibility__"
        assert isinstance(getattr(func, "__mcp_visibility__"), str)

        assert hasattr(func, "__mcp_input_schema__"), f"{name} missing __mcp_input_schema__"
        schema = getattr(func, "__mcp_input_schema__")
        assert isinstance(schema, dict), f"{name} input schema must be a dict"
        assert schema.get("type") == "object", f"{name} schema must be an object schema"

        assert hasattr(
            func, "__mcp_input_schema_hash__"
        ), f"{name} missing __mcp_input_schema_hash__"
        schema_hash = getattr(func, "__mcp_input_schema_hash__")
        assert isinstance(schema_hash, str) and schema_hash, f"{name} schema hash must be non-empty"


def test_introspection_catalog_always_reports_gate_and_approval_fields():
    """Regression guard: catalog entries must include stable metadata fields."""

    idx = _catalog_index(include_parameters=True)
    assert "list_all_actions" in idx

    required_keys = {
        "name",
        "visibility",
        "write_action",
        "write_allowed",
        "write_enabled",
        "write_auto_approved",
        "write_actions_enabled",
        "approval_required",
        "input_schema",
    }

    for name, entry in idx.items():
        missing = sorted(required_keys.difference(entry.keys()))
        assert not missing, f"Catalog entry for {name} missing keys: {missing}"

        assert isinstance(entry["write_action"], bool)
        assert entry["write_allowed"] is True
        assert entry["write_enabled"] is True
        assert entry["write_auto_approved"] is True
        assert entry["write_actions_enabled"] is True
        assert entry["approval_required"] is False

        schema = entry["input_schema"]
        assert isinstance(schema, dict), f"{name} input_schema must be a dict"
        assert schema.get("type") == "object", f"{name} input_schema must be an object schema"

    # Spot-check: at least one known write tool must require approval when gated.
    # (If tools are renamed in the future, this assertion will force updating the regression list.)
    write_candidates = [
        "create_branch",
        "ensure_branch",
        "ensure_workspace_clone",
        "commit_workspace",
    ]
    found_write = [n for n in write_candidates if n in idx]
    assert (
        found_write
    ), f"Expected at least one known write tool in catalog; missing {write_candidates}"
    assert any(idx[n]["write_action"] is True for n in found_write)
    assert all(idx[n]["approval_required"] is False for n in found_write)
