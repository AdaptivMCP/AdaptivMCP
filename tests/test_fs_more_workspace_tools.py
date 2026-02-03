import asyncio
import os

import pytest

import github_mcp.workspace_tools.fs as fs


class DummyWorkspaceTools:
    def __init__(self, repo_dir: str) -> None:
        self.repo_dir = repo_dir

    def _workspace_deps(self):
        async def clone_repo(full_name, ref, preserve_changes=True):  # noqa: ARG001
            return self.repo_dir

        return {"clone_repo": clone_repo}

    def _effective_ref_for_repo(self, full_name: str, ref: str) -> str:  # noqa: ARG002
        return ref


def test_create_workspace_folders_validation_and_success(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    out = asyncio.run(fs.create_workspace_folders("octo/example", paths=None))
    assert out.get("status") == "error"

    # A whitespace path resolves to repo root; it is treated as an existing folder.
    out2 = asyncio.run(fs.create_workspace_folders("octo/example", paths=[" "]))
    assert out2["status"] == "created"
    assert out2["ok"] is True
    assert out2["existing"] == [" "]

    # Creating a folder where a file exists should fail.
    (repo_dir / "afile").write_text("x", encoding="utf-8")
    out2b = asyncio.run(fs.create_workspace_folders("octo/example", paths=["afile"]))
    assert out2b["ok"] is False
    assert any(item["path"] == "afile" for item in out2b["failed"])

    # Create a nested folder.
    out3 = asyncio.run(
        fs.create_workspace_folders(
            "octo/example", paths=["a/b/c"], exist_ok=True, create_parents=True
        )
    )
    assert out3["ok"] is True
    assert out3["created"] == ["a/b/c"]
    assert os.path.isdir(repo_dir / "a" / "b" / "c")

    # Existing folder goes to existing when exist_ok.
    out4 = asyncio.run(
        fs.create_workspace_folders("octo/example", paths=["a/b/c"], exist_ok=True)
    )
    assert out4["existing"] == ["a/b/c"]

    # Existing folder fails when exist_ok=False.
    out5 = asyncio.run(
        fs.create_workspace_folders("octo/example", paths=["a/b/c"], exist_ok=False)
    )
    assert out5["ok"] is False
    assert any(item["path"] == "a/b/c" for item in out5["failed"])


def test_read_workspace_file_sections_and_numbered(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    (repo_dir / "t.txt").write_text("one\n" + "two\n" + "three\n", encoding="utf-8")
    (repo_dir / "bin.dat").write_bytes(b"A\x00B" * 10)

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    missing = asyncio.run(
        fs.read_workspace_file_sections("octo/example", path="missing.txt", max_sections=2)
    )
    assert missing["exists"] is False
    assert missing["sections"]["parts"] == []

    binary = asyncio.run(
        fs.read_workspace_file_sections("octo/example", path="bin.dat", max_sections=2)
    )
    assert binary["exists"] is True
    assert binary["is_binary"] is True
    assert binary["sections"]["parts"] == []

    sec = asyncio.run(
        fs.read_workspace_file_sections(
            "octo/example",
            path="t.txt",
            start_line=1,
            max_sections=1,
            max_lines_per_section=2,
            overlap_lines=0,
        )
    )
    assert sec["exists"] is True
    assert sec["is_binary"] is False
    assert len(sec["sections"]["parts"]) == 1
    assert sec["sections"]["parts"][0]["start_line"] == 1
    assert sec["sections"]["parts"][0]["end_line"] == 2
    assert sec["sections"]["truncated"] is True
    assert sec["sections"]["next_start_line"] == 3

    numbered = asyncio.run(
        fs.read_workspace_file_with_line_numbers(
            "octo/example",
            path="t.txt",
            start_line=2,
            end_line=3,
            separator=": ",
            include_text=True,
        )
    )
    assert numbered["exists"] is True
    assert numbered["numbered"]["start_line"] == 2
    assert numbered["numbered"]["end_line"] == 3
    assert [ln["text"] for ln in numbered["numbered"]["lines"]] == ["two", "three"]
    assert "2: two" in (numbered["numbered"]["text"] or "")


def test_format_numbered_lines_as_text_edge_cases():
    assert fs._format_numbered_lines_as_text([]) == ""

    out = fs._format_numbered_lines_as_text(
        [{"line": 9, "text": "x"}, {"line": 10, "text": "y"}], separator=" | "
    )
    # width should be 2 because line 10 is two digits.
    assert " 9 | x" in out
    assert "10 | y" in out

    out2 = fs._format_numbered_lines_as_text(
        [{"line": 1, "text": "a"}], width=1, separator=None  # type: ignore[arg-type]
    )
    assert out2 == "1: a"
