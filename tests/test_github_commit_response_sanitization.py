import pytest

import main
from github_mcp.github_content import _perform_github_commit


@pytest.mark.asyncio
async def test_perform_github_commit_strips_base64_content(monkeypatch):
    async def fake_github_request(method, path, **kwargs):
        assert method == "PUT"
        assert path.startswith("/repos/")
        return {
            "json": {
                "content": {
                    "name": "file.txt",
                    "path": "file.txt",
                    "sha": "file-sha",
                    "content": "YmFzZTY0LWJsb2I=",
                    "encoding": "base64",
                    "html_url": "https://github.com/o/r/blob/main/file.txt",
                },
                "commit": {
                    "sha": "commit-sha",
                    "html_url": "https://github.com/o/r/commit/commit-sha",
                },
            }
        }

    monkeypatch.setattr(main, "_github_request", fake_github_request)

    out = await _perform_github_commit(
        full_name="o/r",
        branch="main",
        path="file.txt",
        message="msg",
        body_bytes=b"hello",
        sha=None,
        committer=None,
        author=None,
    )

    assert isinstance(out, dict)
    assert "content" in out and isinstance(out["content"], dict)
    assert "content" not in out["content"]
    assert "encoding" not in out["content"]
    assert out["commit"]["sha"] == "commit-sha"
