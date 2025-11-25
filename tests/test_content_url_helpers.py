import asyncio
import httpx
import pytest

from main import GitHubAPIError, _load_body_from_content_url


def test_load_body_from_sandbox_path(tmp_path):
    file_path = tmp_path / "example.txt"
    expected = b"hello sandbox"
    file_path.write_bytes(expected)

    result = asyncio.run(
        _load_body_from_content_url(f"sandbox:{file_path}", context="test")
    )

    assert result == expected


def test_load_body_from_absolute_path(tmp_path):
    file_path = tmp_path / "absolute.txt"
    expected = b"absolute content"
    file_path.write_bytes(expected)

    result = asyncio.run(
        _load_body_from_content_url(str(file_path), context="test")
    )

    assert result == expected


def test_load_body_from_invalid_scheme():
    with pytest.raises(GitHubAPIError):
        asyncio.run(
            _load_body_from_content_url("ftp://example.com/file", context="test")
        )


def test_load_body_from_sandbox_with_rewrite(monkeypatch):
    called = {}

    async def handler(request):
        called["url"] = str(request.url)
        return httpx.Response(200, content=b"rewritten")

    transport = httpx.MockTransport(handler)
    monkeypatch.setenv("SANDBOX_CONTENT_BASE_URL", "https://rewriter.example")
    monkeypatch.setattr(
        "main._http_client_external",
        httpx.AsyncClient(transport=transport, base_url="https://rewriter.example"),
    )

    result = asyncio.run(
        _load_body_from_content_url("sandbox:/missing/file.txt", context="test")
    )

    assert called["url"].endswith("missing/file.txt")
    assert result == b"rewritten"


def test_load_body_from_absolute_with_rewrite(monkeypatch):
    called = {}

    async def handler(request):
        called["url"] = str(request.url)
        return httpx.Response(200, content=b"absolute-rewritten")

    transport = httpx.MockTransport(handler)
    monkeypatch.setenv("SANDBOX_CONTENT_BASE_URL", "https://rewrite-host.example")
    monkeypatch.setattr(
        "main._http_client_external",
        httpx.AsyncClient(transport=transport, base_url="https://rewrite-host.example"),
    )

    result = asyncio.run(
        _load_body_from_content_url("/missing/abs.txt", context="test")
    )

    assert called["url"].endswith("missing/abs.txt")
    assert result == b"absolute-rewritten"
