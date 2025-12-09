import pytest

import main
from main import GitHubAPIError


@pytest.mark.asyncio
async def test_create_file_treats_404_as_missing(monkeypatch):
    async def fake_decode(full_name, path, ref):
        raise GitHubAPIError("status 404")

    async def fake_commit(**kwargs):
        return {"commit": {"sha": "after"}}

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
