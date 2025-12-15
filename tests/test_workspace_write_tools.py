import pytest


@pytest.mark.asyncio
async def test_set_workspace_file_contents_writes_and_reads(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    def fake_ensure_write_allowed(*args, **kwargs):
        return None

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {"clone_repo": fake_clone_repo, "ensure_write_allowed": fake_ensure_write_allowed},
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    res = await tw.set_workspace_file_contents(
        full_name="owner/repo",
        ref="feature",
        path="dir/note.txt",
        content="hello\n",
        create_parents=True,
    )

    assert res.get("status") == "written"
    assert (tmp_path / "dir" / "note.txt").read_text(encoding="utf-8") == "hello\n"
    assert res.get("size_bytes") == len("hello\n".encode("utf-8"))

    read = await tw.get_workspace_file_contents(
        full_name="owner/repo",
        ref="feature",
        path="dir/note.txt",
    )
    assert read["exists"] is True
    assert read["text"] == "hello\n"


@pytest.mark.asyncio
async def test_set_workspace_file_contents_rejects_path_traversal(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    def fake_ensure_write_allowed(*args, **kwargs):
        return None

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {"clone_repo": fake_clone_repo, "ensure_write_allowed": fake_ensure_write_allowed},
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    bad = await tw.set_workspace_file_contents(
        full_name="owner/repo",
        ref="feature",
        path="../evil.txt",
        content="nope",
    )

    assert "error" in bad
    assert bad["error"]["error"] == "ValueError"
