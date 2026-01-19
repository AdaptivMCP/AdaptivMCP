import asyncio

from github_mcp.workspace_tools import rg as workspace_rg


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        return {"clone_repo": clone_repo}

    def _effective_ref_for_repo(self, full_name, ref):
        return ref


def test_rg_list_workspace_files_falls_back_to_python(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("a", encoding="utf-8")
    (repo_dir / "b.txt").write_text("b", encoding="utf-8")
    (repo_dir / ".hidden.txt").write_text("h", encoding="utf-8")
    (repo_dir / "sub").mkdir()
    (repo_dir / "sub" / "c.py").write_text("print('c')", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: False)

    result = asyncio.run(
        workspace_rg.rg_list_workspace_files(
            full_name="octo/example",
            ref="main",
            path="",
            include_hidden=False,
            glob=["*.txt", "*.py"],
            max_results=10,
        )
    )

    assert result.get("error") is None
    assert result["engine"] == "python"
    assert ".hidden.txt" not in result["files"]
    assert "a.txt" in result["files"]
    assert "sub/c.py" in result["files"]


def test_rg_search_workspace_returns_line_numbers_and_context(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("one\nfoo\nthree\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_rg, "_tw", lambda: dummy)
    monkeypatch.setattr(workspace_rg, "_rg_available", lambda: False)

    result = asyncio.run(
        workspace_rg.rg_search_workspace(
            full_name="octo/example",
            ref="main",
            query="foo",
            path="",
            regex=False,
            case_sensitive=True,
            max_results=10,
            context_lines=1,
        )
    )

    assert result.get("error") is None
    assert result["engine"] == "python"
    assert result["matches"]
    m = result["matches"][0]
    assert m["path"] == "a.txt"
    assert m["line"] == 2
    assert m["text"] == "foo"
    assert "excerpt" in m
    ex = m["excerpt"]
    assert ex["start_line"] == 1
    assert ex["end_line"] == 3
    assert [ln["line"] for ln in ex["lines"]] == [1, 2, 3]
