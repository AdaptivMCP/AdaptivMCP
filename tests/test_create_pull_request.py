import pytest

import main


@pytest.mark.asyncio
async def test_create_pull_request_returns_structured_error(monkeypatch):
    monkeypatch.setattr(main.server, "WRITE_ALLOWED", True)

    def fake_effective_ref(full_name, ref):
        return ref

    def fake_ensure_write_allowed(context):
        return None

    async def fake_github_request(*args, **kwargs):
        raise main.GitHubAPIError("boom")

    monkeypatch.setattr(main, "_effective_ref_for_repo", fake_effective_ref)
    monkeypatch.setattr(main.server, "_ensure_write_allowed", fake_ensure_write_allowed)
    monkeypatch.setattr(main, "_github_request", fake_github_request)

    result = await main.create_pull_request(
        full_name="owner/repo", title="title", head="feature", base="main"
    )

    assert "error" in result
    assert result["error"]["context"] == "create_pull_request"
    assert "boom" in result["error"]["message"]
