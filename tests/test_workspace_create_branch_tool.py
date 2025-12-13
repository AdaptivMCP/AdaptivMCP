import pytest


@pytest.mark.asyncio
async def test_workspace_create_branch_runs_git_commands(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    calls = []

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        calls.append(cmd)
        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "run_shell": fake_run_shell,
        },
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)
    monkeypatch.setattr(tw, "_ensure_write_allowed", lambda *a, **k: None)

    res = await tw.workspace_create_branch(
        full_name="owner/repo",
        base_ref="main",
        new_branch="feature/test",
        push=True,
    )

    assert res["new_branch"] == "feature/test"
    assert any(cmd.startswith("git checkout -b") for cmd in calls)
    assert any(cmd.startswith("git push -u origin") for cmd in calls)


@pytest.mark.asyncio
async def test_workspace_create_branch_rejects_invalid_name(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    async def fake_run_shell(cmd, cwd=None, timeout_seconds=300, env=None):
        return {
            "exit_code": 0,
            "timed_out": False,
            "stdout": "",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
        }

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "run_shell": fake_run_shell,
        },
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)
    monkeypatch.setattr(tw, "_ensure_write_allowed", lambda *a, **k: None)

    bad = await tw.workspace_create_branch(
        full_name="owner/repo",
        base_ref="main",
        new_branch="..//bad name",
        push=False,
    )

    assert "error" in bad
    assert bad["error"]["error"] == "ValueError"
