import asyncio
import os


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


def test_delete_workspace_paths_input_validation():
    out = asyncio.run(fs.delete_workspace_paths("octo/example", paths=None))
    assert out.get("status") == "error"
    assert "paths must contain at least one path" in (
        str(out.get("error", "")) + " " + str(out.get("error_detail", {}))
    )

    out2 = asyncio.run(
        fs.delete_workspace_paths(
            "octo/example",
            paths=["ok", 123],  # type: ignore[list-item]
        )
    )
    assert out2.get("status") == "error"
    assert "paths must be a list of strings" in (
        str(out2.get("error", "")) + " " + str(out2.get("error_detail", {}))
    )


def test_delete_workspace_paths_success_missing_and_nonempty_dir(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Files/dirs to delete.
    (repo_dir / "a.txt").write_text("hello", encoding="utf-8")
    empty_dir = repo_dir / "empty"
    empty_dir.mkdir()

    nonempty = repo_dir / "nonempty"
    nonempty.mkdir()
    (nonempty / "x.txt").write_text("x", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    # Non-empty dir without allow_recursive should fail but still delete other paths.
    result = asyncio.run(
        fs.delete_workspace_paths(
            "octo/example",
            paths=["a.txt", "missing.txt", "nonempty"],
            allow_missing=True,
            allow_recursive=False,
        )
    )

    assert result["status"] == "deleted"
    assert result["ref"] == "main"
    assert "a.txt" in result["removed"]
    assert "missing.txt" in result["missing"]
    assert any(item["path"] == "nonempty" for item in result["failed"])
    assert result["ok"] is False

    # With allow_recursive it should delete the directory.
    result2 = asyncio.run(
        fs.delete_workspace_paths(
            "octo/example",
            paths=["nonempty"],
            allow_missing=False,
            allow_recursive=True,
        )
    )
    assert result2["ok"] is True
    assert result2["removed"] == ["nonempty"]
    assert not os.path.exists(repo_dir / "nonempty")

    out = asyncio.run(fs.delete_workspace_folders("octo/example", paths=None))
    assert out.get("status") == "error"
    assert "paths must contain at least one path" in (
        str(out.get("error", "")) + " " + str(out.get("error_detail", {}))
    )

    out2 = asyncio.run(
        fs.delete_workspace_folders(
            "octo/example",
            paths=["ok", 123],  # type: ignore[list-item]
        )
    )
    assert out2.get("status") == "error"
    assert "paths must be a list of strings" in (
        str(out2.get("error", "")) + " " + str(out2.get("error_detail", {}))
    )


def test_delete_workspace_paths_rejects_outside_repo_paths(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    result = asyncio.run(
        fs.delete_workspace_paths(
            "octo/example",
            paths=[str(outside), "../outside.txt"],
            allow_missing=True,
        )
    )

    assert result["status"] == "deleted"
    assert result["ok"] is False
    assert any(item["path"] == str(outside) for item in result["failed"])
    assert any(item["path"] == "../outside.txt" for item in result["failed"])


def test_delete_workspace_folders_non_dir_and_missing(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("hello", encoding="utf-8")

    d = repo_dir / "dir"
    d.mkdir()
    (d / "x.txt").write_text("x", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    # Attempting to delete a file as a folder should fail.
    res = asyncio.run(
        fs.delete_workspace_folders(
            "octo/example",
            paths=["a.txt", "missing", "dir"],
            allow_missing=True,
            allow_recursive=False,
        )
    )
    assert res["status"] == "deleted"
    assert "missing" in res["missing"]
    assert any(item["path"] == "a.txt" for item in res["failed"])
    # Non-empty dir without allow_recursive should fail.
    assert any(item["path"] == "dir" for item in res["failed"])
    assert res["ok"] is False

    # Allow recursive removal.
    res2 = asyncio.run(
        fs.delete_workspace_folders(
            "octo/example",
            paths=["dir"],
            allow_missing=False,
            allow_recursive=True,
        )
    )
    assert res2["ok"] is True
    assert res2["removed"] == ["dir"]


def test_get_workspace_file_contents_success_and_error(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("hello", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    out = asyncio.run(fs.get_workspace_file_contents("octo/example", path="a.txt"))
    assert out["exists"] is True
    assert out["text"] == "hello"
    assert out["encoding"] == "utf-8"

    # Empty path triggers structured error.
    out2 = asyncio.run(fs.get_workspace_file_contents("octo/example", path=""))
    assert out2.get("status") == "error"


def test_get_workspace_files_contents_globs_and_missing(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "a.txt").write_text("a", encoding="utf-8")
    (repo_dir / "b.txt").write_text("b", encoding="utf-8")
    sub = repo_dir / "sub"
    sub.mkdir()
    (sub / "c.txt").write_text("c", encoding="utf-8")

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    out = asyncio.run(
        fs.get_workspace_files_contents(
            "octo/example",
            paths=["*.txt", "sub/*.txt", "missing.txt"],
            expand_globs=True,
            include_missing=True,
        )
    )

    assert out["status"] in {"ok", "partial"}
    returned_paths = {f["path"] for f in out["files"]}
    assert {"a.txt", "b.txt", "sub/c.txt", "missing.txt"}.issubset(returned_paths)
    assert "missing.txt" in out["missing_paths"]
    assert out["summary"]["requested"] == 3
    assert out["summary"]["missing"] >= 1


def test_read_workspace_file_excerpt_missing_dir_binary_and_text(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    # Text file.
    (repo_dir / "t.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")

    # Binary file.
    (repo_dir / "bin.dat").write_bytes(b"A\x00B" * 10)

    # Directory.
    (repo_dir / "adir").mkdir()

    dummy = DummyWorkspaceTools(str(repo_dir))
    monkeypatch.setattr(fs, "_tw", lambda: dummy)

    missing = asyncio.run(
        fs.read_workspace_file_excerpt("octo/example", path="nope.txt", max_lines=10)
    )
    assert missing["exists"] is False

    binary = asyncio.run(
        fs.read_workspace_file_excerpt("octo/example", path="bin.dat", max_lines=10)
    )
    assert binary["exists"] is True
    assert binary["is_binary"] is True
    assert binary["excerpt"]["lines"] == []

    text = asyncio.run(
        fs.read_workspace_file_excerpt(
            "octo/example", path="t.txt", start_line=2, max_lines=2, max_chars=100
        )
    )
    assert text["exists"] is True
    assert text["is_binary"] is False
    assert [ln["text"] for ln in text["excerpt"]["lines"]] == ["two", "three"]

    # Directory should return structured error.
    dir_out = asyncio.run(
        fs.read_workspace_file_excerpt("octo/example", path="adir", max_lines=10)
    )
    assert dir_out.get("status") == "error"
