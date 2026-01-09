from __future__ import annotations

from typing import Any, Dict

import pytest

from github_mcp.mcp_server.user_friendly import build_success_summary
from github_mcp.workspace_tools import commands as commands_mod


@pytest.mark.anyio
async def test_render_shell_returns_terminal_command_shape(monkeypatch: pytest.MonkeyPatch):
    """render_shell should expose terminal_command-like top-level fields.

    This ensures the user_friendly summary logic can consistently report
    exit_code/stdout/stderr for render_shell.
    """

    async def fake_terminal_command(**kwargs: Any) -> Dict[str, Any]:
        # Mimic terminal_command's shape (including UI fields that should be stripped).
        return {
            "workdir": None,
            "command_input": kwargs.get("command"),
            "command": kwargs.get("command"),
            "install": None,
            "result": {"exit_code": 0, "timed_out": False, "stdout": "ok", "stderr": ""},
            "controller_log": ["noise"],
            "summary": {"title": "noise", "bullets": [], "next_steps": []},
            "user_message": "noise",
        }

    async def fake_workspace_create_branch(**kwargs: Any) -> Dict[str, Any]:
        return {"created": True, "branch": kwargs.get("new_branch")}

    # Patch the tools_workspace module used by commands_mod._tw().
    import github_mcp.tools_workspace as tw

    monkeypatch.setattr(tw, "terminal_command", fake_terminal_command)
    monkeypatch.setattr(tw, "workspace_create_branch", fake_workspace_create_branch)

    # Call the undecorated function to avoid schema enforcement.
    out = await commands_mod.render_shell.__wrapped__(
        full_name="owner/repo",
        command="echo hi",
        create_branch="test-branch",
        push_new_branch=True,
        ref="main",
    )

    assert out["full_name"] == "owner/repo"
    assert out["target_ref"] == "test-branch"
    assert out["command_input"] == "echo hi"
    assert out["command"] == "echo hi"
    assert isinstance(out.get("result"), dict)
    assert out["result"].get("exit_code") == 0

    # UI fields from nested terminal_command should not leak.
    assert "controller_log" not in out
    assert "summary" not in out
    assert "user_message" not in out


def test_user_friendly_summary_includes_exit_code_for_render_shell():
    payload = {
        "command_input": "echo hi",
        "result": {"exit_code": 7, "timed_out": False, "stdout": "", "stderr": "boom"},
    }
    summary = build_success_summary("render_shell", payload)
    assert any("Exit code: 7" in b for b in summary.bullets)
