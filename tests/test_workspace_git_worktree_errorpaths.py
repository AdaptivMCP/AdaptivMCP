from __future__ import annotations

from typing import Any

import pytest


def test__clip_text_and_parse_rows_helpers() -> None:
    from github_mcp.workspace_tools import git_worktree

    raw = "abcdef"
    assert git_worktree._clip_text(raw, max_chars=0) == (raw, False)
    assert git_worktree._clip_text(raw, max_chars=6) == (raw, False)
    # Small caps: keep exact prefix, mark truncated.
    assert git_worktree._clip_text(raw, max_chars=3) == ("abc", True)
    # Ellipsis path.
    assert git_worktree._clip_text(raw, max_chars=4) == ("abc…", True)

    rows = git_worktree._parse_tabbed_rows(
        [
            "a\tb\tc",
            "too\tshort",
            "x\ty\tz\textra\tfields",
            "",
        ],
        expected_cols=3,
    )
    assert rows == [["a", "b", "c"], ["x", "y", "z\textra\tfields"]]


def _mk_tw(*, clone_repo: Any, run_shell: Any):
    class _TW:
        def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
            return ref

        def _workspace_deps(self) -> dict[str, Any]:
            return {"clone_repo": clone_repo, "run_shell": run_shell}

    return _TW()


@pytest.mark.anyio
async def test_workspace_git_stage_and_unstage_command_building(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from github_mcp.workspace_tools import git_worktree

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    calls: list[str] = []

    async def clone_repo(_full_name: str, ref: str, preserve_changes: bool = True) -> str:
        assert ref == "main"
        assert preserve_changes is True
        return str(repo_dir)

    async def run_shell(command: str, cwd: str, timeout_seconds: float = 0) -> dict[str, Any]:
        assert cwd == str(repo_dir)
        calls.append(command)
        if command.startswith("git add"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if command.startswith("git reset"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if command == "git diff --cached --name-only":
            return {"exit_code": 0, "stdout": "a.txt\n", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(git_worktree, "_tw", lambda: _mk_tw(clone_repo=clone_repo, run_shell=run_shell))

    out = await git_worktree.workspace_git_stage(full_name="o/r", ref="main", paths=None)
    assert out["ok"] is True
    assert out["command"] == "git add -A"
    assert out["staged_files"] == ["a.txt"]

    out2 = await git_worktree.workspace_git_stage(
        full_name="o/r", ref="main", paths=[" ", ""]
    )
    assert out2["ok"] is True
    assert out2["command"] == "git add -A"

    out3 = await git_worktree.workspace_git_unstage(
        full_name="o/r", ref="main", paths=["a.txt", "b.txt"]
    )
    assert out3["ok"] is True
    assert out3["command"].startswith("git reset --")
    assert "a.txt" in out3["command"] and "b.txt" in out3["command"]
    assert "git reset" in "\n".join(calls)


@pytest.mark.anyio
async def test_workspace_git_show_and_blame_bounds_and_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from github_mcp.workspace_tools import git_worktree

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    calls: list[str] = []

    async def clone_repo(_full_name: str, ref: str, preserve_changes: bool = True) -> str:
        return str(repo_dir)

    async def run_shell(command: str, cwd: str, timeout_seconds: float = 0) -> dict[str, Any]:
        calls.append(command)
        if command.startswith("git checkout"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if command.startswith("git show"):
            return {"exit_code": 0, "stdout": "SHOW\n", "stderr": ""}
        if command.startswith("git blame"):
            return {"exit_code": 0, "stdout": "abcd (A 2024-01-01T00:00:00+00:00 1) x\n", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(git_worktree, "_tw", lambda: _mk_tw(clone_repo=clone_repo, run_shell=run_shell))

    out = await git_worktree.workspace_git_show(
        full_name="o/r",
        ref="main",
        git_ref="HEAD",
        include_patch=False,
        paths=["  a.txt  ", ""],
        max_chars=10,
    )
    assert out["ok"] is True
    assert "--no-patch" in out["command"]
    assert "--" in out["command"]
    assert out["truncated"] is False

    blame = await git_worktree.workspace_git_blame(
        full_name="o/r",
        ref="main",
        path="src/app.py",
        start_line=0,
        end_line=None,
        max_lines=1_000_000,
    )
    assert blame["ok"] is True
    assert blame["start_line"] == 1
    assert blame["end_line"] == 2000
    assert "-L 1,2000" in blame["command"]

    invalid = await git_worktree.workspace_git_blame(full_name="o/r", ref="main", path="")
    assert invalid["ok"] is False


@pytest.mark.anyio
async def test_workspace_git_stash_save_and_apply_like_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from github_mcp.exceptions import GitHubAPIError
    from github_mcp.workspace_tools import git_worktree

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    calls: list[str] = []

    async def clone_repo(_full_name: str, ref: str, preserve_changes: bool = True) -> str:
        return str(repo_dir)

    async def run_shell(command: str, cwd: str, timeout_seconds: float = 0) -> dict[str, Any]:
        calls.append(command)
        if command.startswith("git checkout"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if command.startswith("git stash push"):
            return {"exit_code": 0, "stdout": "Saved", "stderr": ""}
        if command.startswith("git stash pop"):
            return {"exit_code": 0, "stdout": "Popped", "stderr": ""}
        if command.startswith("git stash apply"):
            return {"exit_code": 1, "stdout": "", "stderr": "boom"}
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(git_worktree, "_tw", lambda: _mk_tw(clone_repo=clone_repo, run_shell=run_shell))

    out = await git_worktree.workspace_git_stash_save(
        full_name="o/r",
        ref="main",
        message="wip",
        include_untracked=True,
        keep_index=True,
    )
    assert out["ok"] is True
    assert "git stash push" in out["command"]
    assert "-u" in out["command"]
    assert "--keep-index" in out["command"]
    assert "-m" in out["command"]

    pop = await git_worktree.workspace_git_stash_pop(full_name="o/r", ref="main", stash_ref="stash@{0}")
    assert pop["ok"] is True
    assert pop["command"].startswith("git stash pop")

    # Internal helper should raise on non-zero exit.
    with pytest.raises(GitHubAPIError):
        await git_worktree._workspace_git_stash_apply_like(
            action="apply",
            full_name="o/r",
            effective_ref="main",
            repo_dir=str(repo_dir),
            deps={"run_shell": run_shell},
            t_default=0,
            stash_ref="stash@{0}",
        )


@pytest.mark.anyio
async def test_workspace_git_commit_fetch_clean_push_and_pull(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from github_mcp.workspace_tools import git_worktree

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    calls: list[str] = []

    async def clone_repo(_full_name: str, ref: str, preserve_changes: bool = True) -> str:
        return str(repo_dir)

    async def run_shell(command: str, cwd: str, timeout_seconds: float = 0) -> dict[str, Any]:
        calls.append(command)
        if command.startswith("git checkout"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if command == "git add -A":
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if command.startswith("git commit"):
            return {"exit_code": 0, "stdout": "Committed", "stderr": ""}
        if command == "git rev-parse HEAD":
            return {"exit_code": 0, "stdout": "abc123\n", "stderr": ""}
        if command.startswith("git fetch"):
            return {"exit_code": 0, "stdout": "Fetched", "stderr": ""}
        if command.startswith("git clean"):
            return {"exit_code": 0, "stdout": "Would remove x", "stderr": ""}
        if command == "git fetch --prune origin":
            return {"exit_code": 0, "stdout": "Fetched", "stderr": ""}
        if command.startswith("git pull"):
            return {"exit_code": 0, "stdout": "Pulled", "stderr": ""}
        if command.startswith("git push"):
            return {"exit_code": 0, "stdout": "Pushed", "stderr": ""}
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(git_worktree, "_tw", lambda: _mk_tw(clone_repo=clone_repo, run_shell=run_shell))

    commit = await git_worktree.workspace_git_commit(
        full_name="o/r",
        ref="main",
        message="msg",
        stage_all=True,
        amend=True,
        no_edit=True,
        allow_empty=True,
    )
    assert commit["ok"] is True
    assert commit["sha"] == "abc123"
    assert "--amend" in commit["command"]
    assert "--no-edit" in commit["command"]
    assert "--allow-empty" in commit["command"]

    fetch = await git_worktree.workspace_git_fetch(
        full_name="o/r", ref="main", remote="upstream", prune=False, tags=True
    )
    assert fetch["ok"] is True
    assert fetch["command"].startswith("git fetch")
    assert "--tags" in fetch["command"] and "upstream" in fetch["command"]

    clean = await git_worktree.workspace_git_clean(
        full_name="o/r",
        ref="main",
        dry_run=False,
        remove_directories=False,
        include_ignored=True,
    )
    assert clean["ok"] is True
    assert clean["command"] == "git clean -f -x"

    push = await git_worktree.workspace_git_push(
        full_name="o/r", ref="main", set_upstream=True, force_with_lease=True
    )
    assert push["ok"] is True
    assert "--force-with-lease" in push["command"]
    assert "-u" in push["command"]

    pull = await git_worktree.workspace_git_pull(full_name="o/r", ref="main", strategy="rebase")
    assert pull["ok"] is True
    assert pull["strategy"] == "rebase"
    assert any(cmd == "git fetch --prune origin" for cmd in calls)


@pytest.mark.anyio
async def test_validation_short_circuits_where_applicable(monkeypatch: pytest.MonkeyPatch) -> None:
    from github_mcp.workspace_tools import git_worktree

    class _TW:
        def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
            raise AssertionError("should not be called")

        def _workspace_deps(self) -> dict[str, Any]:
            raise AssertionError("deps should not be called")

    monkeypatch.setattr(git_worktree, "_tw", lambda: _TW())

    out = await git_worktree.workspace_git_commit(full_name="o/r", ref="main", message="")
    assert out["ok"] is False

    out2 = await git_worktree.workspace_git_merge(full_name="o/r", ref="main", target=" ")
    assert out2["ok"] is False

    out3 = await git_worktree.workspace_git_revert(full_name="o/r", ref="main", commits=[])
    assert out3["ok"] is False

