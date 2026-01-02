import pytest

import github_mcp.mcp_server.context as context
from github_mcp.mcp_server import decorators
from github_mcp.mcp_server.errors import AdaptivToolError


def test_preflight_error_logs_tool_event(monkeypatch):
    events: list[dict[str, object]] = []

    def fake_log(payload):
        events.append(dict(payload))

    def fake_validate(*args, **kwargs):
        raise AdaptivToolError(
            code="tool_args_invalid",
            message="bad args",
            category="validation",
            origin="schema",
            retryable=False,
            details={"tool": "sample_tool"},
        )

    class FakeMCP:
        def tool(self, **kwargs):
            def decorator(fn):
                return {"fn": fn, "name": kwargs.get("name")}

            return decorator

    monkeypatch.setattr(decorators, "_log_tool_json_event", fake_log)
    monkeypatch.setattr(decorators, "_validate_tool_args_schema", fake_validate)
    monkeypatch.setattr(decorators, "mcp", FakeMCP())
    monkeypatch.setattr(decorators, "_REGISTERED_MCP_TOOLS", [])

    @decorators.mcp_tool(write_action=False)
    def sample_tool(value: int = 1):
        return value

    with pytest.raises(AdaptivToolError):
        sample_tool(value=1)

    assert any(
        event.get("event") == "tool_call.error" and event.get("phase") == "preflight"
        for event in events
    )


@pytest.mark.asyncio
async def test_terminal_command_error_reports_surface(monkeypatch):
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

    result = await commands.terminal_command(full_name="org/repo")
    assert result["tool_surface"] == "terminal_command"


@pytest.mark.asyncio
async def test_render_shell_error_reports_surface(monkeypatch):
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

    result = await commands.render_shell(full_name="org/repo")
    assert result["tool_surface"] == "render_shell"
