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


def test_compare_workspace_files_include_stats_counts_lines(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "left.txt").write_text("hello\nworld\n", encoding="utf-8")
    (repo_dir / "right.txt").write_text("hello\nthere\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.compare_workspace_files(
            full_name="octo/example",
            ref="feature",
            comparisons=[{"left_path": "left.txt", "right_path": "right.txt"}],
            context_lines=1,
            include_stats=True,
        )
    )

    assert result.get("error") is None
    assert result.get("ok") is True
    comp = result["comparisons"][0]
    assert comp.get("status") == "ok"
    assert comp.get("stats") == {"added": 1, "removed": 1}


def test_compare_workspace_files_include_stats_zero_for_equal(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("same\n", encoding="utf-8")
    (repo_dir / "b.txt").write_text("same\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.compare_workspace_files(
            full_name="octo/example",
            ref="feature",
            comparisons=[{"left_path": "a.txt", "right_path": "b.txt"}],
            include_stats=True,
        )
    )

    assert result.get("error") is None
    assert result.get("ok") is True
    comp = result["comparisons"][0]
    assert comp.get("status") == "ok"
    assert comp.get("diff") == ""
    assert comp.get("stats") == {"added": 0, "removed": 0}
