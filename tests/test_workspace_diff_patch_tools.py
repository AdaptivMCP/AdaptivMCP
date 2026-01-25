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


class DummyPatchTools(DummyWorkspaceTools):
    def __init__(self, repo_dir: str) -> None:
        super().__init__(repo_dir)
        self.patches: list[str] = []

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        async def apply_patch_to_repo(repo_dir, patch):
            self.patches.append(patch)

        return {"clone_repo": clone_repo, "apply_patch_to_repo": apply_patch_to_repo}


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


def test_make_diff_from_text_alias():
    result = asyncio.run(
        workspace_fs.make_diff(
            full_name="octo/example",
            ref="main",
            before="alpha\n",
            after="beta\n",
            fromfile="a.txt",
            tofile="b.txt",
        )
    )

    assert "diff" in result
    assert "-alpha" in result["diff"]
    assert "+beta" in result["diff"]
    assert result.get("diff_stats") == {"added": 1, "removed": 1}


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


def test_make_patch_from_text_alias():
    result = asyncio.run(
        workspace_fs.make_patch(
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


def test_apply_diff_alias_applies_patch(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    dummy = DummyPatchTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    patch = (
        "diff --git a/note.txt b/note.txt\n"
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )

    result = asyncio.run(
        workspace_fs.apply_diff(
            full_name="octo/example",
            ref="main",
            diff=patch,
        )
    )

    assert dummy.patches == [patch]
    assert result.get("status") == "patched"
    assert result.get("patches_applied") == 1
    assert result.get("diff_stats") == {"added": 1, "removed": 1}
