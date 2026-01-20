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


def test_make_workspace_diff_from_path(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "note.txt").write_text("old\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.make_workspace_diff(
            full_name="octo/example",
            ref="main",
            path="note.txt",
            updated_content="new\n",
        )
    )

    diff_text = result.get("diff") or ""
    assert "-old" in diff_text
    assert "+new" in diff_text
    assert result.get("diff_stats") == {"added": 1, "removed": 1}
    assert result.get("ref") == "main"
    assert result.get("path") == "note.txt"


def test_make_workspace_patch_from_text():
    result = asyncio.run(
        workspace_fs.make_workspace_patch(
            full_name="octo/example",
            ref="main",
            before="alpha\n",
            after="beta\n",
            fromfile="a.txt",
            tofile="b.txt",
        )
    )

    assert "patch" in result
    assert "diff" not in result
    assert "-alpha" in result["patch"]
    assert "+beta" in result["patch"]
    assert result.get("diff_stats") == {"added": 1, "removed": 1}
