from __future__ import annotations

import importlib


def _reload_context():
    """Reload github_mcp.mcp_server.context to refresh module state."""
    import github_mcp.mcp_server.context as context

    return importlib.reload(context)


def test_write_gate_always_enabled():
    context = _reload_context()
    assert context.get_write_allowed(refresh_after_seconds=0.0) is True
    assert bool(context.WRITE_ALLOWED) is True


def test_decorators_do_not_block_write_tools_when_gate_is_false():
    _reload_context()

    from github_mcp.mcp_server.decorators import _enforce_write_allowed

    # Read tool is always allowed.
    _enforce_write_allowed("read_tool", write_action=False)

    # Write tool should not be blocked; clients are expected to prompt.
    _enforce_write_allowed("write_tool", write_action=True)


def test_no_write_gate_env_var_in_ci():
    ci = open(".github/workflows/ci.yml", encoding="utf-8").read()
    assert "GITHUB_MCP_WRITE_ALLOWED" not in ci
    # Guard against introducing legacy gates like MCP_WRITE_ALLOWED or WRITE_ALLOWED.
    import re

    assert re.search(r"(^|\s)MCP_WRITE_ALLOWED\s*:", ci, flags=re.MULTILINE) is None
    assert re.search(r"(^|\s)WRITE_ALLOWED\s*:", ci, flags=re.MULTILINE) is None
