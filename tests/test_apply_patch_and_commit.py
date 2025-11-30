import pytest

import main
from main import GitHubAPIError


@pytest.mark.asyncio
async def test_apply_patch_and_commit_creates_new_file(monkeypatch):
    """Patch-based flow should allow creating new files when the Contents API
    returns a 404, using sha_before=None and a create-style commit message.
    """

    decode_calls = []

    async def fake_decode(full_name, path, branch):
        call_index = len(decode_calls)
        decode_calls.append({"full_name": full_name, "path": path, "branch": branch})
        if call_index == 0:
            raise GitHubAPIError(
                "GitHub content request failed with status 404 for /contents/new-file.txt"
            )
        return {
            "text": "first line\nsecond line\n",
            "sha": "after-sha",
            "html_url": "https://example.com/new-file.txt",
        }

    commit_calls = []

    async def fake_commit(**kwargs):
        commit_calls.append({
            "full_name": kwargs["full_name"],
            "path": kwargs["path"],
            "branch": kwargs["branch"],
            "content_bytes": kwargs["body_bytes"],
            "message": kwargs["message"],
            "sha": kwargs["sha"],
        })
        return {"commit": {"sha": "after-sha"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    patch = """--- /dev/null
+++ b/new-file.txt
@@ -0,0 +1,2 @@
+first line
+second line
"""

    result = await main.apply_patch_and_commit(
        full_name="owner/repo",
        path="new-file.txt",
        patch=patch,
        branch="feature-branch",
        return_diff=True,
    )

    assert len(decode_calls) == 2
    assert len(commit_calls) == 1

    commit = commit_calls[0]
    assert commit["full_name"] == "owner/repo"
    assert commit["path"] == "new-file.txt"
    assert commit["branch"] == "feature-branch"
    assert commit["content_bytes"] == b"first line\nsecond line\n"
    assert commit["sha"] is None
    assert commit["message"] == "Create new-file.txt via patch"

    assert result["status"] == "committed"
    assert result["verification"]["sha_before"] is None
    assert result["verification"]["sha_after"] == "after-sha"
    assert "diff" in result
