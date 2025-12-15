import pytest

import main
from main import GitHubAPIError


@pytest.mark.asyncio
async def test_apply_text_update_and_commit_updates_existing_file(monkeypatch):
    decode_calls = []
    decode_results = [
        {
            "text": "old text",
            "json": {"sha": "before-sha"},
            "html_url": "https://example.com/file",
        },
        {
            "text": "new text",
            "json": {"sha": "after-sha"},
            "html_url": "https://example.com/file",
        },
    ]

    async def fake_decode(full_name, path, branch):
        decode_calls.append({"full_name": full_name, "path": path, "branch": branch})
        return decode_results[len(decode_calls) - 1]

    commit_calls = []

    async def fake_commit(**kwargs):
        commit_calls.append(
            {
                "full_name": kwargs["full_name"],
                "path": kwargs["path"],
                "branch": kwargs["branch"],
                "body_bytes": kwargs["body_bytes"],
                "message": kwargs["message"],
                "sha": kwargs["sha"],
            }
        )
        return {"commit": {"sha": "after-sha"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    result = await main.apply_text_update_and_commit(
        full_name="owner/repo",
        path="file.txt",
        updated_content="new text",
        branch="feature-branch",
        message="Custom message",
    )

    assert len(commit_calls) == 1
    assert len(decode_calls) == 2

    commit = commit_calls[0]
    assert commit["path"] == "file.txt"
    assert commit["sha"] == "before-sha"
    assert commit["body_bytes"] == b"new text"

    assert result["status"] == "committed"
    assert result["verification"]["sha_before"] == "before-sha"
    assert result["verification"]["sha_after"] == "after-sha"


@pytest.mark.asyncio
async def test_apply_text_update_and_commit_creates_new_file_on_404(monkeypatch):
    decode_calls = []

    async def fake_decode(full_name, path, branch):
        call_index = len(decode_calls)
        decode_calls.append({"full_name": full_name, "path": path, "branch": branch})
        if call_index == 0:
            raise GitHubAPIError(
                "GitHub content request failed with status 404 for /contents/new-file.txt"
            )
        return {
            "text": "new text",
            "json": {"sha": "after-sha"},
            "html_url": "https://example.com/new-file.txt",
        }

    commit_calls = []

    async def fake_commit(**kwargs):
        commit_calls.append({"sha": kwargs.get("sha"), "message": kwargs.get("message")})
        return {"commit": {"sha": "after-sha"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    result = await main.apply_text_update_and_commit(
        updated_content="new text",
        full_name="owner/repo",
        path="new-file.txt",
        branch="feature-branch",
        message=None,
    )

    assert len(commit_calls) == 1
    assert commit_calls[0]["sha"] is None
    assert commit_calls[0]["message"] == "Create new-file.txt"

    assert result["status"] == "committed"
    assert result["verification"]["sha_before"] is None
    assert result["verification"]["sha_after"] == "after-sha"
