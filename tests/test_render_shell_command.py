import pytest

import github_mcp.tools_workspace as tw
import main


@pytest.mark.asyncio
async def test_render_shell_defaults_to_default_branch(monkeypatch):
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    def fake_default_branch(full_name: str) -> str:
        assert full_name == "owner/repo"
        return "main"

    def fake_effective_ref(full_name: str, ref: str) -> str:
        assert full_name == "owner/repo"
        return ref

    async def fake_terminal_command(**kwargs):
        return {"ran": kwargs}

    monkeypatch.setattr(tw, "_default_branch_for_repo", fake_default_branch)
    monkeypatch.setattr(tw, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(tw, "terminal_command", fake_terminal_command)

    result = await main.render_shell(full_name="owner/repo", command="echo ok")

    assert result["base_ref"] == "main"
    assert result["target_ref"] == "main"
    assert result["branch"] is None
    assert result["command"]["ran"]["ref"] == "main"


@pytest.mark.asyncio
async def test_render_shell_can_create_branch(monkeypatch):
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    branch_calls = []
    terminal_calls = []

    async def fake_workspace_create_branch(**kwargs):
        branch_calls.append(kwargs)
        return {"new_branch": kwargs["new_branch"], "base_ref": kwargs["base_ref"]}

    async def fake_terminal_command(**kwargs):
        terminal_calls.append(kwargs)
        return {"result": {"exit_code": 0}}

    def fake_effective_ref(full_name: str, ref: str) -> str:
        assert full_name == "owner/repo"
        return ref

    monkeypatch.setattr(tw, "_default_branch_for_repo", lambda *_: "main")
    monkeypatch.setattr(tw, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(tw, "workspace_create_branch", fake_workspace_create_branch)
    monkeypatch.setattr(tw, "terminal_command", fake_terminal_command)

    result = await main.render_shell(
        full_name="owner/repo",
        command="echo hi",
        create_branch="feature/render",
    )

    assert branch_calls
    branch_call = branch_calls[-1]
    assert branch_call["base_ref"] == "main"
    assert branch_call["new_branch"] == "feature/render"
    assert result["target_ref"] == "feature/render"
    assert terminal_calls[-1]["ref"] == "feature/render"
