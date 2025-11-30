import pytest

import main
from main import GitHubAPIError


@pytest.mark.asyncio
async def test_decode_github_content_surfaces_effective_ref(monkeypatch):
    def fake_effective_ref(full_name: str, ref: str | None) -> str:
        assert full_name == "owner/repo"
        assert ref is None
        return "issue-137"

    async def fake_github_request(*args, **kwargs):
        raise GitHubAPIError("GitHub API error 404 for GET /repos/owner/repo/contents/main.py")

    monkeypatch.setattr(main, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(main, "_github_request", fake_github_request)

    with pytest.raises(GitHubAPIError) as excinfo:
        await main._decode_github_content("owner/repo", "main.py", None)

    message = str(excinfo.value)
    assert "issue-137" in message
    assert "owner/repo/main.py" in message
