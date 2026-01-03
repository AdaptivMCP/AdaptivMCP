import asyncio
import pytest

import github_mcp.mcp_server.context as context


def test_terminal_command_error_reports_surface(monkeypatch):
    if not context.FASTMCP_AVAILABLE:
        pytest.skip("FastMCP unavailable; workspace tools are not importable.")
    from github_mcp.workspace_tools import commands

    def fake_tw():
        class FakeTW:
            def _workspace_deps(self):
                raise RuntimeError("boom")

        return FakeTW()

    def fake_structured(exc, **kwargs):
        return {"tool_surface": kwargs.get("tool_surface")}

    monkeypatch.setattr(commands, "_tw", fake_tw)
    monkeypatch.setattr(commands, "_structured_tool_error", fake_structured)

    result = asyncio.run(commands.terminal_command(full_name="org/repo"))
    assert result["tool_surface"] == "terminal_command"


def test_render_shell_error_reports_surface(monkeypatch):
    if not context.FASTMCP_AVAILABLE:
        pytest.skip("FastMCP unavailable; workspace tools are not importable.")
    from github_mcp.workspace_tools import commands

    def fake_tw():
        class FakeTW:
            def _resolve_full_name(self, *args, **kwargs):
                raise RuntimeError("boom")

        return FakeTW()

    def fake_structured(exc, **kwargs):
        return {"tool_surface": kwargs.get("tool_surface")}

    monkeypatch.setattr(commands, "_tw", fake_tw)
    monkeypatch.setattr(commands, "_structured_tool_error", fake_structured)

    result = asyncio.run(commands.render_shell(full_name="org/repo"))
    assert result["tool_surface"] == "render_shell"
