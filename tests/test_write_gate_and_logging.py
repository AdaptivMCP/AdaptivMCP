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

    monkeypatch.setattr(commands, "_tw", fake_tw)

    result = asyncio.run(commands.terminal_command(full_name="org/repo"))
    assert result["error"] == "boom"


def test_render_shell_error_reports_surface(monkeypatch):
    if not context.FASTMCP_AVAILABLE:
        pytest.skip("FastMCP unavailable; workspace tools are not importable.")
    from github_mcp.workspace_tools import commands

    def fake_tw():
        class FakeTW:
            def _effective_ref_for_repo(self, *args, **kwargs):
                raise RuntimeError("boom")

        return FakeTW()

    monkeypatch.setattr(commands, "_tw", fake_tw)

    result = asyncio.run(commands.render_shell(full_name="org/repo"))
    assert result["error"] == "boom"
