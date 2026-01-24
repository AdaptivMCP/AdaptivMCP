import asyncio

from github_mcp.workspace_tools import fs as workspace_fs


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        async def apply_patch_to_repo(repo_dir, patch):
            raise AssertionError(
                "apply_patch_to_repo should not be called in these tests"
            )

        return {"clone_repo": clone_repo, "apply_patch_to_repo": apply_patch_to_repo}

    def _effective_ref_for_repo(self, full_name, ref):
        return ref


def test_apply_workspace_operations_preview_only_does_not_mutate(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("hello\nworld\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            preview_only=True,
            operations=[
                {"op": "write", "path": "b.txt", "content": "new\n"},
                {"op": "replace_text", "path": "a.txt", "old": "world", "new": "there"},
                {"op": "delete", "path": "a.txt", "allow_missing": False},
            ],
        )
    )

    # The decorator wrapper strips __log_* fields; we validate outcome via FS.
    assert result.get("error") is None
    assert (repo_dir / "a.txt").read_text(encoding="utf-8") == "hello\nworld\n"
    assert not (repo_dir / "b.txt").exists()


def test_apply_workspace_operations_applies_and_moves(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("one\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            preview_only=False,
            operations=[
                {"op": "write", "path": "b.txt", "content": "two\n"},
                {"op": "move", "src": "b.txt", "dst": "c.txt", "overwrite": False},
                {"op": "delete", "path": "a.txt", "allow_missing": False},
            ],
        )
    )

    assert result.get("error") is None
    assert not (repo_dir / "a.txt").exists()
    assert not (repo_dir / "b.txt").exists()
    assert (repo_dir / "c.txt").read_text(encoding="utf-8") == "two\n"


def test_apply_workspace_operations_rolls_back_on_error(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("stable\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            fail_fast=True,
            rollback_on_error=True,
            preview_only=False,
            operations=[
                {"op": "delete", "path": "a.txt", "allow_missing": False},
                {"op": "unsupported"},
            ],
        )
    )

    assert "error" in result
    # The delete should have been rolled back.
    assert (repo_dir / "a.txt").read_text(encoding="utf-8") == "stable\n"


def test_move_workspace_paths_moves(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "src.txt").write_text("x\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.move_workspace_paths(
            full_name="octo/example",
            ref="feature",
            moves=[{"src": "src.txt", "dst": "dst.txt"}],
        )
    )

    assert result.get("error") is None
    assert not (repo_dir / "src.txt").exists()
    assert (repo_dir / "dst.txt").read_text(encoding="utf-8") == "x\n"
