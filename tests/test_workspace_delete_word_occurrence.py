import asyncio

from github_mcp.workspace_tools import fs as workspace_fs


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        return {"clone_repo": clone_repo}

    def _effective_ref_for_repo(self, full_name, ref):
        return ref


def test_delete_workspace_word_occurrence_out_of_range_noop(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    p = repo_dir / "note.txt"
    original = "foo bar foo\n"
    p.write_text(original, encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    # occurrence is 1-indexed; ask for a non-existent 3rd match.
    result = asyncio.run(
        workspace_fs.delete_workspace_word(
            full_name="octo/example",
            ref="main",
            path="note.txt",
            word="foo",
            occurrence=3,
            replace_all=False,
            case_sensitive=True,
            whole_word=True,
        )
    )

    assert result.get("status") == "noop"
    assert result.get("removed") == ""
    assert result.get("removed_span") is None
    assert p.read_text(encoding="utf-8") == original


def test_delete_workspace_word_invalid_occurrence_returns_structured_error(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "note.txt").write_text("foo\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.delete_workspace_word(
            full_name="octo/example",
            ref="main",
            path="note.txt",
            word="foo",
            occurrence=0,
        )
    )

    # Must not raise (regression for _structured_tool_error kw-arg mismatch).
    assert result.get("status") == "error"
    error_detail = result.get("error_detail") or {}
    assert result.get("context") == "delete_workspace_word"
    assert error_detail.get("category") == "validation"



def test_apply_workspace_operations_delete_word_out_of_range_is_noop(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    p = repo_dir / "note.txt"
    original = "foo foo\n"
    p.write_text(original, encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.apply_workspace_operations(
            full_name="octo/example",
            ref="main",
            operations=[
                {
                    "op": "delete_word",
                    "path": "note.txt",
                    "word": "foo",
                    "occurrence": 5,
                    "replace_all": False,
                    "case_sensitive": True,
                    "whole_word": True,
                }
            ],
            fail_fast=True,
            rollback_on_error=True,
        )
    )

    assert result.get("status") == "ok"
    assert result.get("ok") is True
    assert result.get("results")[0].get("status") == "noop"
    assert p.read_text(encoding="utf-8") == original
