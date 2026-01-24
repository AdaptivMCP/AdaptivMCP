from __future__ import annotations

import base64

import pytest

from github_mcp import github_content
from github_mcp.exceptions import GitHubAPIError


@pytest.mark.anyio
async def test_decode_github_content_large_file_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_request(*_args, **_kwargs):
        return {"json": {"sha": "abc", "size": 123, "download_url": "https://example"}}

    monkeypatch.setattr(github_content, "_request", _fake_request)

    decoded = await github_content._decode_github_content("o/r", "README.md", "main")

    assert decoded["large_file"] is True
    assert decoded["content"] is None
    assert decoded["encoding"] is None
    assert decoded["decoded_bytes"] is None
    assert decoded["size"] == 123
    assert "get_file_excerpt" in decoded["message"]


@pytest.mark.anyio
async def test_decode_github_content_raises_on_invalid_base64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_request(*_args, **_kwargs):
        return {
            "json": {"content": "not-valid-base64", "encoding": "base64", "sha": "abc"}
        }

    monkeypatch.setattr(github_content, "_request", _fake_request)

    with pytest.raises(GitHubAPIError):
        await github_content._decode_github_content("o/r", "README.md", "main")


@pytest.mark.anyio
async def test_decode_github_content_non_utf8_text_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = b"\xff\xfe\xfd"
    payload = base64.b64encode(raw).decode("ascii")

    async def _fake_request(*_args, **_kwargs):
        return {"json": {"content": payload, "encoding": "base64", "sha": "abc"}}

    monkeypatch.setattr(github_content, "_request", _fake_request)
    monkeypatch.setattr(github_content, "ADAPTIV_MCP_INCLUDE_BASE64_CONTENT", False)

    decoded = await github_content._decode_github_content("o/r", "bin.dat", "main")

    assert decoded["decoded_bytes"] == raw
    assert decoded["text"] is None
    assert decoded["size"] == len(raw)


@pytest.mark.anyio
async def test_decode_github_content_returns_full_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"hello world"
    payload = base64.b64encode(body).decode("ascii")

    async def _fake_request(*_args, **_kwargs):
        return {"json": {"content": payload, "encoding": "base64", "sha": "abc"}}

    monkeypatch.setattr(github_content, "_request", _fake_request)
    monkeypatch.setattr(github_content, "ADAPTIV_MCP_INCLUDE_BASE64_CONTENT", True)

    decoded = await github_content._decode_github_content("o/r", "README.md", "main")

    assert decoded["decoded_bytes"] == body
    assert decoded["text"] == "hello world"
    assert decoded["content"] == payload
    assert decoded["encoding"] == "base64"
