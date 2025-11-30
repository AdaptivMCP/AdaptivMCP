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

    async def fake_commit(**kwargs):
        record = {
            "full_name": kwargs["full_name"],
            "path": kwargs["path"],
            "branch": kwargs["branch"],
            # Map internal body_bytes naming to the content_bytes key used in assertions.
            "content_bytes": kwargs["body_bytes"],
            "message": kwargs["message"],
            "sha": kwargs["sha"],
        }
        commit_calls.append(record)
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
        manual_override=True,
    )
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

    async def fake_commit(**kwargs):
        record = {
            "full_name": kwargs["full_name"],
            "path": kwargs["path"],
            "branch": kwargs["branch"],
            "content_bytes": kwargs["body_bytes"],
            "message": kwargs["message"],
            "sha": kwargs["sha"],
        }
        commit_calls.append(record)
        return {"commit": {"sha": "after-sha"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    result = await main.apply_text_update_and_commit(
    result = await main.apply_text_update_and_commit(
        updated_content="new text",
        branch="feature-branch",
        message=None,
        return_diff=True,
        manual_override=True,
    )
@pytest.mark.asyncio

    result = await main.apply_text_update_and_commit(
        full_name="owner/repo",
        path="new-file.txt",
        updated_content="new text",
        branch="feature-branch",
        message=None,
        return_diff=True,
        manual_override=True,
    )
        return {"commit": {"sha": "after-sha"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    with pytest.raises(RuntimeError) as excinfo:
        await main.apply_text_update_and_commit(
            full_name="owner/repo",
            path="file.txt",
            updated_content="new text",
            branch="feature-branch",
            message="Custom message",
            return_diff=True,
        )

    msg = str(excinfo.value)
    assert "disabled for automated bulk edits" in msg
    assert "build_unified_diff + apply_patch_and_commit" in msg

