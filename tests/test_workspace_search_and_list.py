import os

import pytest


@pytest.mark.asyncio
async def test_list_workspace_files_basic_and_limits(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / ".hidden.txt").write_text("h", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "ignored").write_text("x", encoding="utf-8")

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    monkeypatch.setattr(tw, "_workspace_deps", lambda: {"clone_repo": fake_clone_repo})
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    res = await tw.list_workspace_files(full_name="owner/repo", ref="feature")
    assert res["truncated"] is False
    assert "a.txt" in res["files"]
    assert "b.txt" in res["files"]
    assert ".hidden.txt" not in res["files"]
    assert os.path.join(".git", "ignored") not in res["files"]

    res_hidden = await tw.list_workspace_files(
        full_name="owner/repo", ref="feature", include_hidden=True
    )
    assert ".hidden.txt" in res_hidden["files"]

    res_trunc = await tw.list_workspace_files(
        full_name="owner/repo", ref="feature", max_files=1
    )
    assert res_trunc["truncated"] is True
    assert len(res_trunc["files"]) == 1


@pytest.mark.asyncio
async def test_search_workspace_basic_and_safety(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    (tmp_path / "note.txt").write_text("hello world\nsecond line\n", encoding="utf-8")
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01\x02")
    (tmp_path / "big.txt").write_text("hello" + "x" * 5000, encoding="utf-8")

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    monkeypatch.setattr(tw, "_workspace_deps", lambda: {"clone_repo": fake_clone_repo})
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    res = await tw.search_workspace(
        full_name="owner/repo",
        ref="feature",
        query="hello",
        max_results=10,
        max_file_bytes=1000,  # excludes big.txt, includes note.txt
    )

    files = {r["file"] for r in res["results"]}
    assert "note.txt" in files
    assert "big.txt" not in files
    assert "bin.dat" not in files

    # Path traversal should be rejected.
    bad = await tw.search_workspace(
        full_name="owner/repo",
        ref="feature",
        query="hello",
        path="../",
    )
    assert "error" in bad
    assert bad["error"]["error"] == "ValueError"
