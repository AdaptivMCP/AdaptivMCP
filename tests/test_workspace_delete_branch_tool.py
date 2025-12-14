import pytest


@pytest.mark.asyncio
async def test_workspace_delete_branch_runs_git_commands(monkeypatch, tmp_path):
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
    monkeypatch.setattr(tw, "_default_branch_for_repo", lambda full_name: "main")
    monkeypatch.setattr(tw, "_ensure_write_allowed", lambda *a, **k: None)

    res = await tw.workspace_delete_branch(
        full_name="owner/repo",
        branch="feature/test-delete",
    )

    assert res["deleted_branch"] == "feature/test-delete"
    assert any(cmd.startswith("git checkout ") for cmd in calls)
    assert any("git push origin --delete feature/test-delete" in cmd for cmd in calls)
    assert any("git branch -D feature/test-delete" in cmd for cmd in calls)


@pytest.mark.asyncio
async def test_workspace_delete_branch_rejects_default_branch(monkeypatch, tmp_path):
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
    monkeypatch.setattr(tw, "_default_branch_for_repo", lambda full_name: "main")
    monkeypatch.setattr(tw, "_ensure_write_allowed", lambda *a, **k: None)

    result = await tw.workspace_delete_branch(
        full_name="owner/repo",
        branch="main",
    )

    assert "error" in result
    assert result["error"]["error"] == "GitHubAPIError"
