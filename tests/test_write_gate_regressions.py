from __future__ import annotations

import importlib
import types


def _reload_context(monkeypatch, value: str | None):
    """Reload github_mcp.mcp_server.context after setting env var.

    This ensures import-time defaults and WRITE_ALLOWED behaviors stay consistent
    even if future refactors introduce caching.
    """

    if value is None:
        monkeypatch.delenv("GITHUB_MCP_WRITE_ALLOWED", raising=False)
    else:
        monkeypatch.setenv("GITHUB_MCP_WRITE_ALLOWED", value)

    import github_mcp.mcp_server.context as context

    return importlib.reload(context)


def test_write_gate_env_var_is_single_source_of_truth(monkeypatch):
    # Default: true when unset
    context = _reload_context(monkeypatch, None)
    assert context.get_write_allowed(refresh_after_seconds=0.0) is True
    assert bool(context.WRITE_ALLOWED) is True

    # Explicit false variants
    context = _reload_context(monkeypatch, "false")
    assert context.get_write_allowed(refresh_after_seconds=0.0) is False
    assert bool(context.WRITE_ALLOWED) is False

    # Explicit true variants
    context = _reload_context(monkeypatch, "true")
    assert context.get_write_allowed(refresh_after_seconds=0.0) is True
    assert bool(context.WRITE_ALLOWED) is True


def test_decorators_do_not_block_write_tools_when_gate_is_false(monkeypatch):
    # Ensure write is not auto-approved.
    _reload_context(monkeypatch, "false")

    from github_mcp.mcp_server.decorators import _enforce_write_allowed

    # Read tool is always allowed.
    _enforce_write_allowed("read_tool", write_action=False)

    # Write tool should not be blocked; clients are expected to prompt.
    _enforce_write_allowed("write_tool", write_action=True)


def test_actions_compat_write_enabled_tracks_env_gate(monkeypatch):
    # Create a fake server with registered tools.
    read_tool = types.SimpleNamespace(name="read_tool", write_action=False, description="read")
    write_tool = types.SimpleNamespace(name="write_tool", write_action=True, description="write")

    def read_fn():
        return "ok"

    def write_fn():
        return "ok"

    server = types.SimpleNamespace(
        _REGISTERED_MCP_TOOLS=[(read_tool, read_fn), (write_tool, write_fn)],
        _normalize_input_schema=lambda _obj: {"type": "object", "properties": {}},
    )

    # Patch introspection so actions_compat uses a deterministic catalog.
    import github_mcp.http_routes.actions_compat as actions_compat

    def fake_catalog(*_args, **_kwargs):
        return {
            "tools": [
                {
                    "name": "read_tool",
                    "description": "read",
                    "write_action": False,
                    "write_enabled": True,
                    "write_allowed": True,
                    "input_schema": {"type": "object", "properties": {}},
                    "visibility": "public",
                },
                {
                    "name": "write_tool",
                    "description": "write",
                    "write_action": True,
                    # write_enabled/write_allowed should be overwritten by env gate,
                    # but we set them true here to catch regressions.
                    "write_enabled": True,
                    "write_allowed": True,
                    "input_schema": {"type": "object", "properties": {}},
                    "visibility": "public",
                },
            ]
        }

    monkeypatch.setattr(actions_compat, "list_all_actions", fake_catalog)

    # Gate off.
    monkeypatch.setenv("GITHUB_MCP_WRITE_ALLOWED", "false")
    # Ensure actions_compat reads the updated env via its imported helper.
    importlib.reload(actions_compat)
    actions = actions_compat.serialize_actions_for_compatibility(server)
    idx = {a["name"]: a for a in actions}
    assert idx["read_tool"]["write_enabled"] is True
    assert idx["read_tool"]["write_allowed"] is True
    assert idx["write_tool"]["write_action"] is True
    assert idx["write_tool"]["write_enabled"] is True
    assert idx["write_tool"]["write_allowed"] is False

    # Gate on.
    monkeypatch.setenv("GITHUB_MCP_WRITE_ALLOWED", "true")
    importlib.reload(actions_compat)
    actions = actions_compat.serialize_actions_for_compatibility(server)
    idx = {a["name"]: a for a in actions}
    assert idx["write_tool"]["write_enabled"] is True
    assert idx["write_tool"]["write_allowed"] is True


def test_no_legacy_write_gate_env_var_in_ci():
    # CI must use only GITHUB_MCP_WRITE_ALLOWED.
    ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
    assert "GITHUB_MCP_WRITE_ALLOWED" in ci
    # Guard against introducing legacy gates like MCP_WRITE_ALLOWED or WRITE_ALLOWED.
    # Note: we must not fail on the substring inside GITHUB_MCP_WRITE_ALLOWED.
    import re

    assert re.search(r"(^|\s)MCP_WRITE_ALLOWED\s*:", ci, flags=re.MULTILINE) is None
    assert re.search(r"(^|\s)WRITE_ALLOWED\s*:", ci, flags=re.MULTILINE) is None
