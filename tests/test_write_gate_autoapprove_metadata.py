from __future__ import annotations

import os

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


def test_introspection_catalog_always_reports_gate_and_approval_fields(monkeypatch):
    """Regression guard: catalog entries must include stable write-gate metadata.

    This protects client behavior (prompting/auto-approval) for any future tools.
    """

    # Force approval-gated mode.
    monkeypatch.setenv("GITHUB_MCP_WRITE_ALLOWED", "false")

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
        assert entry["write_auto_approved"] is False
        assert entry["write_actions_enabled"] is False

        # Approval is required exactly when: write_action and not auto-approved.
        assert entry["approval_required"] == (entry["write_action"] and not entry["write_auto_approved"])

        schema = entry["input_schema"]
        assert isinstance(schema, dict), f"{name} input_schema must be a dict"
        assert schema.get("type") == "object", f"{name} input_schema must be an object schema"

    # Spot-check: at least one known write tool must require approval when gated.
    # (If tools are renamed in the future, this assertion will force updating the regression list.)
    write_candidates = ["create_branch", "ensure_branch", "ensure_workspace_clone", "commit_workspace"]
    found_write = [n for n in write_candidates if n in idx]
    assert found_write, f"Expected at least one known write tool in catalog; missing {write_candidates}"
    assert any(idx[n]["write_action"] is True for n in found_write)
    assert any(idx[n]["approval_required"] is True for n in found_write)


def test_write_auto_approved_flips_with_env_var(monkeypatch):
    """Regression guard: auto-approval follows only GITHUB_MCP_WRITE_ALLOWED."""

    idx = _catalog_index(include_parameters=False)

    # "true" => writes auto-approved => approval_required False for all tools.
    monkeypatch.setenv("GITHUB_MCP_WRITE_ALLOWED", "true")
    idx_true = _catalog_index(include_parameters=False)
    assert all(entry.get("write_auto_approved") is True for entry in idx_true.values())
    assert all(entry.get("approval_required") is False for entry in idx_true.values())

    # "false" => approval required for write tools.
    monkeypatch.setenv("GITHUB_MCP_WRITE_ALLOWED", "false")
    idx_false = _catalog_index(include_parameters=False)
    assert all(entry.get("write_auto_approved") is False for entry in idx_false.values())
    assert any(entry.get("approval_required") is True for entry in idx_false.values())

    # Keep test isolation stable in case other tests assume default.
    monkeypatch.setenv("GITHUB_MCP_WRITE_ALLOWED", os.environ.get("GITHUB_MCP_WRITE_ALLOWED", "true"))
