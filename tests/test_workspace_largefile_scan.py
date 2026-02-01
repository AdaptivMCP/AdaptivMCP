import asyncio

from github_mcp.workspace_tools import fs as workspace_fs
from github_mcp.workspace_tools import listing as workspace_listing


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes):
            return self.repo_dir

        return {"clone_repo": clone_repo}

    def _resolve_full_name(self, full_name, owner=None, repo=None):
        return full_name or "octo/example"

    def _resolve_ref(self, ref, branch=None):
        return branch or ref

    def _effective_ref_for_repo(self, full_name, ref):
        return ref


def test_get_workspace_file_contents_reads_full_file_when_limits_disabled(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    p = repo_dir / "big.txt"
    p.write_text("x" * 10_000, encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    # Disable limits.
    result = asyncio.run(
        workspace_fs.get_workspace_file_contents(
            full_name="octo/example",
            ref="feature",
            path="big.txt",
            max_chars=0,
            max_bytes=0,
        )
    )

    assert result.get("error") is None
    assert result["exists"] is True
    assert result["truncated"] is False
    assert len(result["text"]) == 10_000
    assert result["max_chars"] == 0
    assert result["max_bytes"] is None


def test_read_workspace_file_excerpt_returns_line_numbers_and_limits(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    p = repo_dir / "lines.txt"
    p.write_text("".join(f"line-{i}\n" for i in range(1, 501)), encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.read_workspace_file_excerpt(
            full_name="octo/example",
            ref="feature",
            path="lines.txt",
            start_line=100,
            max_lines=3,
            max_chars=1000,
        )
    )

    assert result.get("error") is None
    assert result["exists"] is True
    excerpt = result["excerpt"]
    assert excerpt["start_line"] == 100
    assert excerpt["end_line"] == 102
    assert [ln["line"] for ln in excerpt["lines"]] == [100, 101, 102]
    assert excerpt["lines"][0]["text"] == "line-100"

    # Now force max_chars truncation.
    result2 = asyncio.run(
        workspace_fs.read_workspace_file_excerpt(
            full_name="octo/example",
            ref="feature",
            path="lines.txt",
            start_line=1,
            max_lines=200,
            max_chars=10,
        )
    )
    assert result2.get("error") is None
    assert result2["excerpt"]["truncated"] is True


def test_read_workspace_file_with_line_numbers_formats_text_and_end_line(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    p = repo_dir / "lines.txt"
    p.write_text("".join(f"line-{i}\n" for i in range(1, 21)), encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.read_workspace_file_with_line_numbers(
            full_name="octo/example",
            ref="feature",
            path="lines.txt",
            start_line=9,
            end_line=11,
            separator=" | ",
            include_text=True,
        )
    )

    assert result.get("error") is None
    assert result["exists"] is True
    numbered = result["numbered"]
    assert numbered["start_line"] == 9
    assert numbered["end_line"] == 11
    assert [ln["line"] for ln in numbered["lines"]] == [9, 10, 11]
    assert numbered["text"] == " 9 | line-9\n10 | line-10\n11 | line-11"

    result2 = asyncio.run(
        workspace_fs.read_workspace_file_with_line_numbers(
            full_name="octo/example",
            ref="feature",
            path="lines.txt",
            start_line=1,
            end_line=1,
            include_text=False,
        )
    )
    assert result2.get("error") is None
    assert result2["numbered"]["text"] is None


def test_read_workspace_file_with_line_numbers_sets_next_start_line_on_truncation(
    tmp_path, monkeypatch
):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    p = repo_dir / "lines.txt"
    p.write_text("".join(f"line-{i}\n" for i in range(1, 501)), encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_fs, "_tw", lambda: dummy)

    result = asyncio.run(
        workspace_fs.read_workspace_file_with_line_numbers(
            full_name="octo/example",
            ref="feature",
            path="lines.txt",
            start_line=1,
            max_lines=3,
            max_chars=1_000,
        )
    )
    assert result.get("error") is None
    numbered = result["numbered"]
    assert numbered["truncated"] is True
    assert numbered["next_start_line"] == 4


def test_search_workspace_pagination_cursor(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("foo\nfoo\nfoo\nfoo\nfoo\n", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    page1 = asyncio.run(
        workspace_listing.search_workspace(
            query="foo",
            path="a.txt",
            max_results=2,
            cursor=0,
        )
    )
    assert page1.get("error") is None
    assert len(page1["results"]) == 2
    assert page1["truncated"] is True
    assert page1["next_cursor"] == 2

    page2 = asyncio.run(
        workspace_listing.search_workspace(
            query="foo",
            path="a.txt",
            max_results=2,
            cursor=2,
        )
    )
    assert page2.get("error") is None
    assert len(page2["results"]) == 2
    assert page2["truncated"] is True
    assert page2["next_cursor"] == 4

    page3 = asyncio.run(
        workspace_listing.search_workspace(
            query="foo",
            path="a.txt",
            max_results=2,
            cursor=4,
        )
    )
    assert page3.get("error") is None
    assert len(page3["results"]) == 1
    assert page3["truncated"] is False
    assert page3["next_cursor"] is None


def test_list_workspace_files_pagination_cursor(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("a", encoding="utf-8")
    (repo_dir / "b.txt").write_text("b", encoding="utf-8")
    (repo_dir / "c.txt").write_text("c", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    page1 = asyncio.run(
        workspace_listing.list_workspace_files(
            path="",
            max_files=2,
            cursor=0,
        )
    )
    assert page1.get("error") is None
    assert len(page1["files"]) == 2
    assert page1["truncated"] is True
    assert page1["next_cursor"] == 2

    page2 = asyncio.run(
        workspace_listing.list_workspace_files(
            path="",
            max_files=2,
            cursor=2,
        )
    )
    assert page2.get("error") is None
    assert len(page2["files"]) == 1
    assert page2["truncated"] is False
    assert page2["next_cursor"] is None


def test_find_workspace_paths_glob_and_pagination(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "a.py").write_text("print('a')", encoding="utf-8")
    (repo_dir / "src" / "b.py").write_text("print('b')", encoding="utf-8")
    (repo_dir / "src" / "c.txt").write_text("no", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(workspace_listing, "_tw", lambda: dummy)

    page1 = asyncio.run(
        workspace_listing.find_workspace_paths(
            pattern="*.py",
            path="src",
            pattern_type="glob",
            include_dirs=False,
            include_files=True,
            max_results=1,
            cursor=0,
        )
    )
    assert page1.get("error") is None
    assert len(page1["results"]) == 1
    assert page1["truncated"] is True
    assert page1["next_cursor"] == 1

    page2 = asyncio.run(
        workspace_listing.find_workspace_paths(
            pattern="*.py",
            path="src",
            pattern_type="glob",
            include_dirs=False,
            include_files=True,
            max_results=10,
            cursor=1,
        )
    )
    assert page2.get("error") is None
    assert len(page2["results"]) == 1
    assert page2["truncated"] is False
    assert page2["next_cursor"] is None
