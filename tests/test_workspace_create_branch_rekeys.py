from __future__ import annotations

import os
import shutil
import tempfile
from typing import Any

import pytest


@pytest.mark.anyio
async def test_workspace_create_branch_rekeys_workspace_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Creating a branch should not "lose" uncommitted edits.

    The workspace mirror is keyed by ref. Historically, the tool created a new
    branch in the base ref directory and returned, leaving uncommitted edits in
    the base directory. Subsequent calls using ref=<new_branch> would point at a
    different directory and appear to lose work.

    This test asserts the working copy is moved to the new branch mirror dir and
    the base mirror is recreated.
    """

    from github_mcp.workspace_tools import git_ops

    class _TW:
        def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
            return ref

        def _workspace_deps(self) -> dict[str, Any]:
            return deps

    with tempfile.TemporaryDirectory() as td:
        base_dir = os.path.join(td, "repo-main")
        new_dir = os.path.join(td, "repo-feature")

        os.makedirs(base_dir, exist_ok=True)
        # Simulate an uncommitted local edit.
        with open(os.path.join(base_dir, "local.txt"), "w", encoding="utf-8") as f:
            f.write("hello")

        async def clone_repo(full_name: str, ref: str, preserve_changes: bool = True) -> str:
            assert full_name == "octo-org/octo-repo"
            assert ref in {"main", "feature/test"}
            if ref == "main":
                if not preserve_changes:
                    shutil.rmtree(base_dir, ignore_errors=True)
                os.makedirs(base_dir, exist_ok=True)
                if not preserve_changes:
                    with open(os.path.join(base_dir, "clean.txt"), "w", encoding="utf-8") as f:
                        f.write("clean")
                return base_dir
            os.makedirs(new_dir, exist_ok=True)
            return new_dir

        async def run_shell(command: str, cwd: str, timeout_seconds: float = 0) -> dict[str, Any]:
            # Ensure we are running commands in the base dir prior to re-key.
            assert cwd in {base_dir, new_dir}
            if command.startswith("git checkout -b"):
                return {"exit_code": 0, "stdout": "", "stderr": ""}
            if command.startswith("git push -u origin"):
                return {"exit_code": 0, "stdout": "", "stderr": ""}
            raise AssertionError(f"Unexpected command: {command}")

        deps: dict[str, Any] = {"clone_repo": clone_repo, "run_shell": run_shell}

        monkeypatch.setattr(git_ops, "_tw", lambda: _TW())

        # Route workspace path resolution for the new branch to `new_dir`.
        monkeypatch.setattr(
            git_ops,
            "_workspace_path",
            lambda full_name, ref: new_dir if ref == "feature/test" else base_dir,
        )

        res = await git_ops.workspace_create_branch(
            full_name="octo-org/octo-repo",
            base_ref="main",
            new_branch="feature/test",
            push=True,
        )

        assert res["base_ref"] == "main"
        assert res["new_branch"] == "feature/test"
        assert res["moved_workspace"] is True
        assert os.path.abspath(res["new_repo_dir"]) == os.path.abspath(new_dir)
        assert os.path.abspath(res["base_repo_dir"]) == os.path.abspath(base_dir)

        # The uncommitted edit should now live in the *new* branch directory.
        assert os.path.exists(os.path.join(new_dir, "local.txt"))
        assert not os.path.exists(os.path.join(base_dir, "local.txt"))
        # Base dir was recreated clean.
        assert os.path.exists(os.path.join(base_dir, "clean.txt"))


@pytest.mark.anyio
async def test_workspace_create_branch_errors_if_target_mirror_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from github_mcp.workspace_tools import git_ops

    class _TW:
        def _effective_ref_for_repo(self, _full_name: str, ref: str) -> str:
            return ref

        def _workspace_deps(self) -> dict[str, Any]:
            return deps

    with tempfile.TemporaryDirectory() as td:
        base_dir = os.path.join(td, "repo-main")
        new_dir = os.path.join(td, "repo-feature")
        os.makedirs(base_dir, exist_ok=True)
        os.makedirs(new_dir, exist_ok=True)  # pre-existing target dir

        async def clone_repo(full_name: str, ref: str, preserve_changes: bool = True) -> str:
            assert full_name == "octo-org/octo-repo"
            return base_dir

        async def run_shell(command: str, cwd: str, timeout_seconds: float = 0) -> dict[str, Any]:
            if command.startswith("git checkout -b"):
                return {"exit_code": 0, "stdout": "", "stderr": ""}
            return {"exit_code": 0, "stdout": "", "stderr": ""}

        deps: dict[str, Any] = {"clone_repo": clone_repo, "run_shell": run_shell}

        monkeypatch.setattr(git_ops, "_tw", lambda: _TW())
        monkeypatch.setattr(git_ops, "_workspace_path", lambda _full_name, _ref: new_dir)

        res = await git_ops.workspace_create_branch(
            full_name="octo-org/octo-repo",
            base_ref="main",
            new_branch="feature/test",
            push=False,
        )

        assert res["status"] == "error"
        assert res["ok"] is False
        assert "already exists" in (res.get("error") or "").lower()
