import pytest

import main
from main import GitHubAPIError


@pytest.mark.asyncio
async def test_apply_text_update_and_commit_updates_existing_file(monkeypatch):
    """When the target file exists, the helper should:
    - read the current text,
    - call _perform_github_commit with the prior SHA,
    - re-read the file to verify sha_after, and
    - return a committed status with verification data.
    """

    decode_calls = []
    decode_results = [
        {"text": "old text", "sha": "before-sha", "html_url": "https://example.com/file"},
        {"text": "new text", "sha": "after-sha", "html_url": "https://example.com/file"},
    ]

    async def fake_decode(full_name, path, branch):
        decode_calls.append({"full_name": full_name, "path": path, "branch": branch})
        return decode_results[len(decode_calls) - 1]

    commit_calls = []

    async def fake_commit(full_name, path, branch, content_bytes, message, sha):
        commit_calls.append(
            {
                "full_name": full_name,
                "path": path,
                "branch": branch,
                "content_bytes": content_bytes,
                "message": message,
                "sha": sha,
            }
        )
        return {"commit": {"sha": "after-sha"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    result = await main.apply_text_update_and_commit(
        full_name="owner/repo",
        path="file.txt",
        updated_content="new text",
        branch="feature-branch",
        message="Custom message",
        return_diff=True,
    )

    # We expect one commit and two decodes (before and after).
    assert len(commit_calls) == 1
    assert len(decode_calls) == 2

    commit = commit_calls[0]
    assert commit["full_name"] == "owner/repo"
    assert commit["path"] == "file.txt"
    assert commit["branch"] == "feature-branch"
    assert commit["content_bytes"] == b"new text"
    assert commit["message"] == "Custom message"
    assert commit["sha"] == "before-sha"

    assert result["status"] == "committed"
    assert result["verification"]["sha_before"] == "before-sha"
    assert result["verification"]["sha_after"] == "after-sha"


@pytest.mark.asyncio
async def test_apply_text_update_and_commit_creates_new_file_on_404(monkeypatch):
    """When the initial read returns a 404 from the GitHub Contents API,
    apply_text_update_and_commit should treat the file as new, commit with
    sha_before = None, and then verify using a second successful read.
    """

    decode_calls = []

    async def fake_decode(full_name, path, branch):
        call_index = len(decode_calls)
        decode_calls.append({"full_name": full_name, "path": path, "branch": branch})
        if call_index == 0:
            # First call simulates a 404 from the Contents API.
            raise GitHubAPIError("GitHub content request failed with status 404 for /contents/new-file.txt")
        # Second call represents the post-commit verification read.
        return {"text": "new text", "sha": "after-sha", "html_url": "https://example.com/new-file.txt"}

    commit_calls = []

    async def fake_commit(full_name, path, branch, content_bytes, message, sha):
        commit_calls.append(
            {
                "full_name": full_name,
                "path": path,
                "branch": branch,
                "content_bytes": content_bytes,
                "message": message,
                "sha": sha,
            }
        )
        return {"commit": {"sha": "after-sha"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    result = await main.apply_text_update_and_commit(
        full_name="owner/repo",
        path="new-file.txt",
        updated_content="new text",
        branch="feature-branch",
        message=None,
        return_diff=True,
    )

    # We expect one commit and two decode attempts (404, then success).
    assert len(commit_calls) == 1
    assert len(decode_calls) == 2

    commit = commit_calls[0]
    assert commit["full_name"] == "owner/repo"
    assert commit["path"] == "new-file.txt"
    assert commit["branch"] == "feature-branch"
    assert commit["content_bytes"] == b"new text"
    # For a new file, sha should be None and the generated commit message
    # should follow the "Create <path>" pattern.
    assert commit["sha"] is None
    assert commit["message"] == "Create new-file.txt"

    assert result["status"] == "committed"
    assert result["verification"]["sha_before"] is None
    assert result["verification"]["sha_after"] == "after-sha"
    # The diff is not validated in detail here, only that it is present
    # when return_diff is True.
    assert "diff" in result
