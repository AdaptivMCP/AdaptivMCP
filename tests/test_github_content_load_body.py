from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass
class _DummyHTTPResponse:
    status_code: int
    content: bytes = b""
    text: str = ""


class _DummyHTTPClient:
    def __init__(self, response: _DummyHTTPResponse):
        self._response = response
        self.last_url: str | None = None

    async def get(self, url: str):
        self.last_url = url
        return self._response


@pytest.mark.asyncio
async def test_strip_large_fields_from_commit_response_removes_inline_content():
    from github_mcp.github_content import _strip_large_fields_from_commit_response

    cleaned = _strip_large_fields_from_commit_response(
        {
            "content": {
                "content": "BIGBASE64",
                "encoding": "base64",
                "sha": "abc",
            },
            "commit": {"sha": "deadbeef"},
        }
    )

    assert cleaned["content"].get("content") is None
    assert cleaned["content"].get("encoding") is None
    assert cleaned["content"]["sha"] == "abc"
    assert cleaned["commit"]["sha"] == "deadbeef"


@pytest.mark.asyncio
async def test_load_body_from_content_url_github_happy_path(monkeypatch):
    from github_mcp import github_content

    async def _fake_decode(*, full_name: str, path: str, ref: str | None = None):
        assert full_name == "owner/repo"
        assert path == "path/to/file.txt"
        assert ref == "dev"
        return {"decoded_bytes": b"hello"}

    monkeypatch.setattr(github_content, "_decode_github_content", _fake_decode)

    body = await github_content._load_body_from_content_url(
        "github:owner/repo:path/to/file.txt@dev",
        context="test",
    )
    assert body == b"hello"


@pytest.mark.asyncio
async def test_load_body_from_content_url_github_invalid_spec_raises():
    from github_mcp.exceptions import GitHubAPIError
    from github_mcp.github_content import _load_body_from_content_url

    with pytest.raises(GitHubAPIError):
        await _load_body_from_content_url("github:ownerrepo:path", context="x")
    with pytest.raises(GitHubAPIError):
        await _load_body_from_content_url("github:owner/repo", context="x")
    with pytest.raises(GitHubAPIError):
        await _load_body_from_content_url("github:owner/repo:@ref", context="x")


@pytest.mark.asyncio
async def test_load_body_from_content_url_reads_sandbox_local_file(tmp_path):
    from github_mcp.github_content import _load_body_from_content_url

    f = tmp_path / "payload.bin"
    f.write_bytes(b"abc123")

    body = await _load_body_from_content_url(f"sandbox:{str(f)}", context="test")
    assert body == b"abc123"


@pytest.mark.asyncio
async def test_load_body_from_content_url_rejects_empty_sandbox_prefix():
    from github_mcp.exceptions import GitHubAPIError
    from github_mcp.github_content import _load_body_from_content_url

    with pytest.raises(GitHubAPIError, match="sandbox: content_url must include"):
        await _load_body_from_content_url("sandbox:", context="test")
    with pytest.raises(GitHubAPIError, match="sandbox: content_url must include"):
        await _load_body_from_content_url("sandbox:   ", context="test")

@pytest.mark.asyncio
async def test_load_body_from_content_url_sandbox_missing_uses_rewrite(
    monkeypatch, tmp_path
):
    from github_mcp import github_content

    missing = tmp_path / "does-not-exist.txt"
    monkeypatch.setattr(
        github_content, "SANDBOX_CONTENT_BASE_URL", "https://sandbox.test"
    )
    monkeypatch.setattr(
        github_content,
        "_external_client_instance",
        lambda: _DummyHTTPClient(
            _DummyHTTPResponse(status_code=200, content=b"rewritten")
        ),
    )

    body = await github_content._load_body_from_content_url(
        f"sandbox:{str(missing)}",
        context="test",
    )
    assert body == b"rewritten"


@pytest.mark.asyncio
async def test_perform_github_commit_typecheck_and_strips_payload(monkeypatch):
    from github_mcp import github_content

    with pytest.raises(TypeError):
        await github_content._perform_github_commit(
            "o/r",
            branch="main",
            path="a.txt",
            message="m",
            body_bytes="not-bytes",  # type: ignore[arg-type]
            sha=None,
        )

    async def _fake_request(method: str, path: str, **kwargs):
        assert method == "PUT"
        assert path == "/repos/o/r/contents/a.txt"
        payload = kwargs.get("json_body")
        assert payload["message"] == "m"
        assert payload["branch"] == "main"
        assert "content" in payload
        return {
            "json": {
                "content": {"content": "BIG", "encoding": "base64", "sha": "s"},
                "commit": {"sha": "c"},
            }
        }

    monkeypatch.setattr(github_content, "_request", _fake_request)
    monkeypatch.setattr(
        github_content, "_normalize_repo_path_for_repo", lambda _r, p: p
    )

    cleaned = await github_content._perform_github_commit(
        "o/r",
        branch="main",
        path="a.txt",
        message="m",
        body_bytes=b"hi",
        sha=None,
    )
    assert cleaned["content"].get("content") is None
    assert cleaned["content"].get("encoding") is None
    assert cleaned["commit"]["sha"] == "c"
