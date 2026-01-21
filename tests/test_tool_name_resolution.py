from __future__ import annotations

from typing import Any


def test_find_registered_tool_resolves_common_name_variants(monkeypatch: Any) -> None:
    from github_mcp.mcp_server import registry as mcp_registry

    class Tool:
        name = "terminal_command"

    def func(**_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    monkeypatch.setattr(mcp_registry, "_REGISTERED_MCP_TOOLS", [(Tool(), func)])

    # Hyphenated variant.
    assert mcp_registry._find_registered_tool("terminal-command") is not None

    # Leading slash / URL-ish variant.
    assert mcp_registry._find_registered_tool("/terminal_command") is not None

    # Full MCP-style URI variant.
    assert mcp_registry._find_registered_tool("/tools/terminal-command") is not None

    # Module-qualified variant.
    assert (
        mcp_registry._find_registered_tool("github_mcp.workspace_tools.git_ops.terminal_command")
        is not None
    )

    # Case variants.
    assert mcp_registry._find_registered_tool("Terminal_Command") is not None


def test_find_registered_tool_does_not_silently_choose_ambiguous_matches(monkeypatch: Any) -> None:
    from github_mcp.mcp_server import registry as mcp_registry

    class ToolA:
        name = "foo_bar"

    class ToolB:
        name = "FooBar"

    def func_a(**_kwargs: Any) -> dict[str, Any]:
        return {"ok": "a"}

    def func_b(**_kwargs: Any) -> dict[str, Any]:
        return {"ok": "b"}

    monkeypatch.setattr(
        mcp_registry, "_REGISTERED_MCP_TOOLS", [(ToolA(), func_a), (ToolB(), func_b)]
    )

    # This canonicalizes to the same name as both tools.
    assert mcp_registry._find_registered_tool("foo-bar") is None
