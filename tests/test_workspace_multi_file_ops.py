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


def test_apply_workspace_operations_preview_only_move_existing_file_then_edit(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("hello world\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            preview_only=True,
            operations=[
                {"op": "move", "src": "a.txt", "dst": "b.txt", "overwrite": False},
                {"op": "replace_text", "path": "b.txt", "old": "world", "new": "there"},
            ],
        )
    )

    assert result.get("error") is None
    statuses = [entry.get("status") for entry in result.get("results", [])]
    assert statuses == ["ok", "ok"]

    # preview_only should not mutate the filesystem.
    assert (repo_dir / "a.txt").read_text(encoding="utf-8") == "hello world\n"
    assert not (repo_dir / "b.txt").exists()


def test_apply_workspace_operations_delete_directory_reports_error_and_does_not_mutate(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "adir").mkdir()
    (repo_dir / "adir" / "inner.txt").write_text("hi\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            fail_fast=False,
            rollback_on_error=True,
            preview_only=False,
            operations=[
                {"op": "delete", "path": "adir", "allow_missing": False},
            ],
        )
    )

    assert result.get("error") is None
    assert result.get("ok") is False
    assert result.get("status") == "partial"
    assert result.get("results")[0]["status"] == "error"
    # Directory should remain.
    assert (repo_dir / "adir").is_dir()
    assert (repo_dir / "adir" / "inner.txt").read_text(encoding="utf-8") == "hi\n"


def test_apply_workspace_operations_replace_text_on_directory_reports_relative_error(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "adir").mkdir()

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            fail_fast=False,
            rollback_on_error=True,
            preview_only=False,
            operations=[
                {"op": "replace_text", "path": "adir", "old": "x", "new": "y"},
            ],
        )
    )

    assert result.get("error") is None
    assert result.get("ok") is False
    assert result.get("status") == "partial"

    entry = result.get("results")[0]
    assert entry["status"] == "error"
    err = entry.get("error") or ""
    assert "adir" in err
    assert str(repo_dir) not in err
    assert (repo_dir / "adir").is_dir()


def test_apply_workspace_operations_write_on_directory_reports_relative_error(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "adir").mkdir()

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            fail_fast=False,
            rollback_on_error=True,
            preview_only=False,
            operations=[
                {"op": "write", "path": "adir", "content": "hello\n"},
            ],
        )
    )

    assert result.get("error") is None
    assert result.get("ok") is False
    assert result.get("status") == "partial"

    entry = result.get("results")[0]
    assert entry["status"] == "error"
    err = entry.get("error") or ""
    assert "adir" in err
    assert str(repo_dir) not in err
    assert (repo_dir / "adir").is_dir()


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


def test_apply_workspace_operations_preview_only_chained_ops_on_new_file(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            preview_only=True,
            operations=[
                {"op": "write", "path": "new.txt", "content": "hello world\n"},
                {
                    "op": "delete_word",
                    "path": "new.txt",
                    "word": "world",
                    "whole_word": True,
                },
                {"op": "replace_text", "path": "new.txt", "old": "hello", "new": "hi"},
                {
                    "op": "move",
                    "src": "new.txt",
                    "dst": "moved.txt",
                    "overwrite": False,
                },
                {"op": "delete", "path": "moved.txt", "allow_missing": False},
            ],
        )
    )

    assert result.get("error") is None
    assert result.get("ok") is True
    assert not (repo_dir / "new.txt").exists()
    assert not (repo_dir / "moved.txt").exists()

    statuses = [entry.get("status") for entry in result.get("results", [])]
    assert statuses == ["ok", "ok", "ok", "ok", "ok"]


def test_apply_workspace_operations_chained_ops_on_new_file(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="feature",
            preview_only=False,
            operations=[
                {"op": "write", "path": "new.txt", "content": "hello world\n"},
                {
                    "op": "delete_word",
                    "path": "new.txt",
                    "word": "world",
                    "whole_word": True,
                },
                {"op": "replace_text", "path": "new.txt", "old": "hello", "new": "hi"},
                {
                    "op": "move",
                    "src": "new.txt",
                    "dst": "moved.txt",
                    "overwrite": False,
                },
            ],
        )
    )

    assert result.get("error") is None
    assert result.get("ok") is True
    assert not (repo_dir / "new.txt").exists()
    assert (repo_dir / "moved.txt").read_text(encoding="utf-8") == "hi \n"


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
