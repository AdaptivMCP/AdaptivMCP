from __future__ import annotations

import pytest


def test_resolve_full_name_requires_owner_and_repo_together() -> None:
    """Regression: reject partial owner/repo identifiers.

    Several workspace git tools accept either:
    - full_name ("owner/repo"), OR
    - owner + repo together.

    Historically, passing only owner or only repo could silently fall back to
    the controller repo, which is unsafe and confusing. Ensure we fail fast.
    """

    from github_mcp.exceptions import UsageError
    from github_mcp.workspace_tools._shared import _resolve_full_name

    with pytest.raises(UsageError):
        _resolve_full_name(None, owner="octo", repo=None)

    with pytest.raises(UsageError):
        _resolve_full_name(None, owner=None, repo="example")


def test_resolve_full_name_accepts_owner_repo_and_strips() -> None:
    from github_mcp.workspace_tools._shared import _resolve_full_name

    assert _resolve_full_name(None, owner="  octo  ", repo="  example  ") == "octo/example"


def test_ensure_workspace_clone_schema_does_not_require_full_name(monkeypatch) -> None:
    """ensure_workspace_clone should accept the controller default when full_name is omitted.

    This guards against overly-strict schema validation in MCP clients.
    """

    # Import main to ensure tool registration.
    import main  # noqa: F401
    from github_mcp.main_tools import introspection

    monkeypatch.setenv("ADAPTIV_MCP_AUTO_APPROVE", "true")
    catalog = introspection.list_all_actions(include_parameters=True, compact=False)
    tools = catalog.get("tools", []) or []
    entry = next((t for t in tools if t.get("name") == "ensure_workspace_clone"), None)
    assert entry is not None, "Expected ensure_workspace_clone to be registered"

    schema = entry.get("input_schema") or entry.get("inputSchema") or {}
    assert isinstance(schema, dict)
    required = set(schema.get("required") or [])
    assert "full_name" not in required

    props = schema.get("properties") or {}
    for key in ("full_name", "ref", "reset"):
        assert key in props, f"Expected schema to include '{key}'"

    # Schema ergonomics intentionally hide legacy aliases.
    assert "owner" not in props
    assert "repo" not in props
    assert "branch" not in props
