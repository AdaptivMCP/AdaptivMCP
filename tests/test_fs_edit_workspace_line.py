import asyncio

import github_mcp.workspace_tools.fs as fs


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        return {"clone_repo": clone_repo}

    def _effective_ref_for_repo(self, full_name, ref):
        return ref


def test_edit_workspace_line_replace_preserves_missing_eol(tmp_path, monkeypatch) -> None:
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    path = repo_dir / "note.txt"
    path.write_text("hello", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    result = asyncio.run(
        fs.edit_workspace_line(
            full_name="octo/example",
            ref="main",
            path="note.txt",
            operation="replace",
            line_number=1,
            text="world",
        )
    )

    assert result.get("status") == "edited"
    assert path.read_text(encoding="utf-8") == "world"
