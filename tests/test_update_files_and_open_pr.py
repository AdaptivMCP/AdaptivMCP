import pytest

import main


@pytest.mark.asyncio
async def test_update_files_and_open_pr_returns_structured_error(monkeypatch):
    monkeypatch.setattr(main, "WRITE_ALLOWED", True)

    async def fake_ensure_branch(*args, **kwargs):
        return None

    async def fake_resolve_sha(*args, **kwargs):
        return None

    async def fake_commit(*args, **kwargs):
        return {"ok": True}

    async def fake_create_pr(*args, **kwargs):
        return {"number": 1}

    monkeypatch.setattr(main, "ensure_branch", fake_ensure_branch)
    monkeypatch.setattr(main, "_resolve_file_sha", fake_resolve_sha)
    monkeypatch.setattr(main, "_perform_github_commit", fake_commit)
    monkeypatch.setattr(main, "create_pull_request", fake_create_pr)

    result = await main.update_files_and_open_pr(
        full_name="owner/repo",
        title="Test",
        files=[{"path": "missing.md", "content_url": "/definitely/not/here.txt"}],
        base_branch="main",
        new_branch="ally/test",
    )

    assert "error" in result
    assert result["error"]["context"].startswith("update_files_and_open_pr")
    assert result["error"]["path"] == "missing.md"
    assert "not found" in result["error"]["message"].lower()
