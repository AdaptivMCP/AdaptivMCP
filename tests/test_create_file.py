import pytest

import main
from main import GitHubAPIError


@pytest.mark.asyncio
async def test_create_file_treats_404_as_missing(monkeypatch):
    calls = {"decode": []}

    async def fake_decode(full_name, path, ref):
        calls["decode"].append((full_name, path, ref))
        # Simulate the GitHub Contents API returning 404 on the initial preflight
        # read, then succeeding after the file has been created.
        if len(calls["decode"]) == 1:
            raise GitHubAPIError("status 404")
        return {"text": "hello", "json": {"sha": "after"}}

    async def fake_commit(**kwargs):
        return {"content": {"sha": "after"}, "commit": {"sha": "after"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    result = await main.create_file(
        full_name="owner/repo",
        path="index.md",
        content="hello",
        branch="feature",
    )

    assert result["status"] == "created"
    # We should have tried to read before and after the commit.
    assert calls["decode"] == [
        ("owner/repo", "index.md", "feature"),
        ("owner/repo", "index.md", "feature"),
    ]


@pytest.mark.asyncio
async def test_create_file_raises_when_file_exists(monkeypatch):
    async def fake_decode(full_name, path, ref):
        return {"text": "existing", "json": {"sha": "before"}}

    monkeypatch.setattr(main, "_decode_github_content", fake_decode)
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    with pytest.raises(GitHubAPIError):
        await main.create_file(
            full_name="owner/repo",
            path="index.md",
            content="hello",
            branch="feature",
        )
