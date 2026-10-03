from __future__ import annotations

import asyncio


def test_shell_children_scrub_github_credentials(monkeypatch):
    from github_mcp import workspace

    monkeypatch.setenv("GITHUB_TOKEN", "parent-secret")
    monkeypatch.setenv("GH_TOKEN", "parent-gh-secret")

    result = asyncio.run(
        workspace._run_shell(
            "python -c 'import os; print(os.getenv(\"GITHUB_TOKEN\")); print(os.getenv(\"GH_TOKEN\"))'",
            timeout_seconds=10,
        )
    )

    assert result["exit_code"] == 0
    assert result["stdout"].splitlines() == ["None", "None"]


def test_authenticated_git_command_disables_repo_execution_hooks():
    from github_mcp import workspace

    command = workspace._authenticated_git_command("git fetch origin --prune")

    assert "core.hooksPath=/dev/null" in command
    assert "core.fsmonitor=false" in command
    assert "core.pager=cat" in command
    assert command.endswith("fetch origin --prune")


def test_authenticated_git_command_rejects_config_overrides():
    from github_mcp import workspace

    for command in (
        "git -c core.sshCommand=evil fetch origin",
        "git --config-env=http.extraHeader=SECRET fetch origin",
        "git --config=core.hooksPath=/tmp/hooks fetch origin",
    ):
        try:
            workspace._authenticated_git_command(command)
        except Exception as exc:
            assert "configuration" in str(exc).lower()
        else:
            raise AssertionError("unsafe git configuration override was accepted")


def test_authenticated_git_runner_keeps_credentials_out_of_generic_shell(monkeypatch):
    from github_mcp import workspace
    from github_mcp.workspace_tools import _shared

    captured = {}

    async def fake_run_shell(cmd, *, cwd=None, timeout_seconds=0, env=None):
        captured["cmd"] = cmd
        captured["env"] = dict(env or {})
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(workspace, "_run_shell", fake_run_shell)
    monkeypatch.setattr(workspace, "_get_github_token", lambda: "secret-token")

    result = asyncio.run(
        workspace._run_git_authenticated(
            "git push origin HEAD:feature",
            cwd="/tmp/repo",
            timeout_seconds=10,
        )
    )

    assert result["exit_code"] == 0
    assert captured["env"]["GIT_HTTP_EXTRAHEADER"].startswith("Authorization: Basic ")
    assert captured["env"]["GIT_CONFIG_NOSYSTEM"] == "1"
    assert captured["env"]["GIT_CONFIG_GLOBAL"]
    assert "core.hooksPath=/dev/null" in captured["cmd"]


def test_workspace_shell_rejects_composed_git_commands(monkeypatch):
    import main
    from github_mcp.workspace_tools import _shared

    calls = []

    async def fake_run_shell(cmd, *, cwd=None, timeout_seconds=0, env=None):
        calls.append((cmd, env))
        return {"exit_code": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(main, "_run_shell", fake_run_shell)
    deps = _shared._workspace_deps()

    result = asyncio.run(
        deps["run_shell"](
            "echo safe && git push origin HEAD:main",
            cwd="/tmp/repo",
            timeout_seconds=10,
        )
    )

    assert result["exit_code"] == 126
    assert not calls


def test_workspace_shell_does_not_add_git_credentials(monkeypatch):
    import main
    from github_mcp.workspace_tools import _shared

    calls = []

    async def fake_run_shell(cmd, *, cwd=None, timeout_seconds=0, env=None):
        calls.append(dict(env or {}))
        return {"exit_code": 0, "stdout": "ok", "stderr": ""}

    monkeypatch.setattr(main, "_run_shell", fake_run_shell)
    monkeypatch.setattr(
        _shared,
        "_run_git_authenticated",
        lambda *args, **kwargs: None,
    )
    deps = _shared._workspace_deps()

    result = asyncio.run(
        deps["run_shell"](
            "git status",
            cwd="/tmp/repo",
            timeout_seconds=10,
            env={"EXISTING": "1"},
        )
    )

    assert result["exit_code"] == 0
    assert calls[0]["EXISTING"] == "1"
    assert "GIT_HTTP_EXTRAHEADER" not in calls[0]
