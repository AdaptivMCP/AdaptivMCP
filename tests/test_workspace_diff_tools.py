import pytest


@pytest.mark.asyncio
async def test_get_workspace_file_contents_reads_file(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    monkeypatch.setattr(tw, "_workspace_deps", lambda: {"clone_repo": fake_clone_repo})
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    result = await tw.get_workspace_file_contents(
        full_name="owner/repo",
        ref="feature",
        path="a.txt",
    )

    assert result["exists"] is True
    assert result["text"] == "hello"
    assert result["path"] == "a.txt"
    assert result["full_name"] == "owner/repo"
    assert result["ref"] == "feature"


@pytest.mark.asyncio
async def test_build_unified_diff_from_workspace(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    (tmp_path / "a.txt").write_text("one\n", encoding="utf-8")

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    monkeypatch.setattr(tw, "_workspace_deps", lambda: {"clone_repo": fake_clone_repo})
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    result = await tw.build_unified_diff_from_workspace(
        full_name="owner/repo",
        ref="feature",
        path="a.txt",
        updated_content="two\n",
        context_lines=3,
    )

    patch = result["patch"]
    assert "+two" in patch
    assert "-one" in patch


@pytest.mark.asyncio
async def test_apply_patch_to_workspace_file_rejects_multi_file(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    async def fake_apply_patch(repo_dir, patch):
        return None

    def fake_ensure_write_allowed(context):
        return None

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "apply_patch_to_repo": fake_apply_patch,
            "ensure_write_allowed": fake_ensure_write_allowed,
        },
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    multifile_patch = """diff --git a/a.txt b/a.txt
--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-one
+two
diff --git a/b.txt b/b.txt
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-x
+y
"""

    result = await tw.apply_patch_to_workspace_file(
        full_name="owner/repo",
        ref="feature",
        path="a.txt",
        patch=multifile_patch,
    )

    assert "error" in result
    assert result["error"]["error"] == "ValueError"
    assert "touch exactly one file" in result["error"]["message"]


@pytest.mark.asyncio
async def test_apply_patch_to_workspace_file_rejects_path_mismatch(monkeypatch, tmp_path):
    from github_mcp import tools_workspace as tw

    async def fake_clone_repo(full_name, ref, preserve_changes=True):
        return str(tmp_path)

    async def fake_apply_patch(repo_dir, patch):
        return None

    def fake_ensure_write_allowed(context):
        return None

    monkeypatch.setattr(
        tw,
        "_workspace_deps",
        lambda: {
            "clone_repo": fake_clone_repo,
            "apply_patch_to_repo": fake_apply_patch,
            "ensure_write_allowed": fake_ensure_write_allowed,
        },
    )
    monkeypatch.setattr(tw, "_effective_ref_for_repo", lambda full_name, ref: ref)

    patch = """diff --git a/b.txt b/b.txt
--- a/b.txt
+++ b/b.txt
@@ -1 +1 @@
-one
+two
"""

    result = await tw.apply_patch_to_workspace_file(
        full_name="owner/repo",
        ref="feature",
        path="a.txt",
        patch=patch,
    )

    assert "error" in result
    assert result["error"]["error"] == "ValueError"
    assert "path mismatch" in result["error"]["message"]
