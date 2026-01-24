from __future__ import annotations

import os
from typing import Any

import pytest


@pytest.mark.anyio
async def test_workspace_git_log_parses_commits(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from github_mcp.workspace_tools import git_worktree

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    calls: list[tuple[str, str | None]] = []

    async def clone_repo(
        _full_name: str, ref: str, preserve_changes: bool = True
    ) -> str:
        assert ref == "main"
        assert preserve_changes is True
        return str(repo_dir)

    async def run_shell(
        command: str, cwd: str, timeout_seconds: float = 0
    ) -> dict[str, Any]:
        calls.append((command, cwd))
        if command.startswith("git checkout"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if command.startswith("git log"):
            return {
                "exit_code": 0,
                "stdout": "a" * 40
                + "\tAlice\t2024-01-01T00:00:00+00:00\tInitial\n"
                + "b" * 40
                + "\tBob\t2024-01-02T00:00:00+00:00\tSecond\n",
                "stderr": "",
            }
        raise AssertionError(f"Unexpected command: {command}")

    class _TW:
        def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
            return ref

        def _workspace_deps(self) -> dict[str, Any]:
            return {"clone_repo": clone_repo, "run_shell": run_shell}

    monkeypatch.setattr(git_worktree, "_tw", lambda: _TW())

    out = await git_worktree.workspace_git_log(
        full_name="octo-org/octo-repo",
        ref="main",
        rev_range="HEAD",
        max_entries=10,
    )

    assert out["ok"] is True
    assert len(out["commits"]) == 2
    assert out["commits"][0]["author"] == "Alice"
    assert out["commits"][1]["subject"] == "Second"
    assert any("git log" in c[0] for c in calls)


@pytest.mark.anyio
async def test_workspace_git_branches_parses_refs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from github_mcp.workspace_tools import git_worktree

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    async def clone_repo(
        _full_name: str, ref: str, preserve_changes: bool = True
    ) -> str:
        assert ref == "main"
        return str(repo_dir)

    async def run_shell(
        command: str, cwd: str, timeout_seconds: float = 0
    ) -> dict[str, Any]:
        if command.startswith("git checkout"):
            return {"exit_code": 0, "stdout": "", "stderr": ""}
        if command.startswith("git for-each-ref"):
            return {
                "exit_code": 0,
                "stdout": "refs/heads/main\tmain\t" + "a" * 40 + "\t\t\t*\n",
                "stderr": "",
            }
        raise AssertionError(f"Unexpected command: {command}")

    class _TW:
        def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
            return ref

        def _workspace_deps(self) -> dict[str, Any]:
            return {"clone_repo": clone_repo, "run_shell": run_shell}

    monkeypatch.setattr(git_worktree, "_tw", lambda: _TW())

    out = await git_worktree.workspace_git_branches(
        full_name="octo-org/octo-repo", ref="main"
    )
    assert out["ok"] is True
    assert out["branches"][0]["name"] == "main"
    assert out["branches"][0]["is_head"] is True


@pytest.mark.anyio
async def test_workspace_git_checkout_rekeys_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkout should move the working copy to the new ref mirror path."""

    import shutil
    import tempfile

    from github_mcp.workspace_tools import git_worktree

    class _TW:
        def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
            return ref

        def _workspace_deps(self) -> dict[str, Any]:
            return deps

    with tempfile.TemporaryDirectory() as td:
        base_dir = os.path.join(td, "repo-main")
        target_dir = os.path.join(td, "repo-feature")

        os.makedirs(base_dir, exist_ok=True)
        with open(os.path.join(base_dir, "local.txt"), "w", encoding="utf-8") as f:
            f.write("hi")

        async def clone_repo(
            full_name: str, ref: str, preserve_changes: bool = True
        ) -> str:
            assert full_name == "octo-org/octo-repo"
            assert ref in {"main"}
            if ref == "main":
                if not preserve_changes:
                    shutil.rmtree(base_dir, ignore_errors=True)
                os.makedirs(base_dir, exist_ok=True)
                if not preserve_changes:
                    with open(
                        os.path.join(base_dir, "clean.txt"), "w", encoding="utf-8"
                    ) as f:
                        f.write("clean")
                return base_dir
            raise AssertionError(f"Unexpected ref: {ref}")

        async def run_shell(
            command: str, cwd: str, timeout_seconds: float = 0
        ) -> dict[str, Any]:
            assert cwd == base_dir
            if command.startswith("git checkout"):
                return {"exit_code": 0, "stdout": "", "stderr": ""}
            if command.startswith("git push -u origin"):
                return {"exit_code": 0, "stdout": "", "stderr": ""}
            return {"exit_code": 0, "stdout": "ok", "stderr": ""}

        deps: dict[str, Any] = {"clone_repo": clone_repo, "run_shell": run_shell}

        monkeypatch.setattr(git_worktree, "_tw", lambda: _TW())
        monkeypatch.setattr(
            git_worktree, "_workspace_path", lambda _fn, _ref: target_dir
        )

        res = await git_worktree.workspace_git_checkout(
            full_name="octo-org/octo-repo",
            ref="main",
            target="feature/test",
            create=False,
            rekey_workspace=True,
            push=False,
        )

        assert res["ok"] is True
        assert res["moved_workspace"] is True
        assert os.path.exists(os.path.join(target_dir, "local.txt"))
        assert not os.path.exists(os.path.join(base_dir, "local.txt"))
        assert os.path.exists(os.path.join(base_dir, "clean.txt"))
