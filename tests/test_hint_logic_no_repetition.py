from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_workspace_git_apply_error_sets_hint_without_appending_to_message(
    tmp_path, monkeypatch
):
    from github_mcp import workspace
    from github_mcp.exceptions import GitHubAPIError

    async def _fake_run_shell(*_args, **_kwargs):
        return {"exit_code": 1, "stderr": "Only garbage was found in the patch input."}

    monkeypatch.setattr(workspace, "_run_shell", _fake_run_shell)
    monkeypatch.setattr(
        workspace, "_patch_has_hunk_header_with_ranges", lambda _p: False
    )
    monkeypatch.setattr(workspace, "_looks_like_rangeless_git_patch", lambda _p: False)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    patch = """diff --git a/a.txt b/a.txt
index 0000000..1111111 100644
--- a/a.txt
+++ b/a.txt
@@
+hello
"""

    with pytest.raises(GitHubAPIError) as excinfo:
        await workspace._apply_patch_to_repo(str(repo_dir), patch)

    exc = excinfo.value
    # Message should remain single-purpose (no duplicated hint text).
    assert "git apply failed" in str(exc)
    assert "Patch hunks appear" not in str(exc)

    hint = getattr(exc, "hint", None)
    assert isinstance(hint, str)
    assert "Patch hunks appear" in hint


@pytest.mark.asyncio
async def test_load_body_absolute_path_missing_has_no_hint(tmp_path):
    from github_mcp.exceptions import GitHubAPIError
    from github_mcp.github_content import _load_body_from_content_url

    missing = tmp_path / "missing.bin"

    with pytest.raises(GitHubAPIError) as excinfo:
        await _load_body_from_content_url(str(missing), context="test")

    exc = excinfo.value
    assert getattr(exc, "hint", None) is None
