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


def test_load_body_from_sandbox_missing_without_rewrite():
    with pytest.raises(GitHubAPIError) as excinfo:
        asyncio.run(
            _load_body_from_content_url(
                "sandbox:/not/available.txt", context="missing"
            )
        )

    message = str(excinfo.value)
    assert "SANDBOX_CONTENT_BASE_URL" in message
    assert "http(s) URL" in message


def test_load_body_from_github_url_with_ref(monkeypatch):
    called = {}

    async def fake_decode(full_name, path, ref=None):
        called['full_name'] = full_name
        called['path'] = path
        called['ref'] = ref
        return {'decoded_bytes': b'github-bytes', 'sha': 'sha'}

    monkeypatch.setattr('github_mcp.github_content._decode_github_content', fake_decode)

    result = asyncio.run(
        _load_body_from_content_url(
            'github:owner/repo:path/to/file.txt@branch',
            context='github-test',
        )
    )

    assert result == b'github-bytes'
    assert called['full_name'] == 'owner/repo'
    assert called['path'] == 'path/to/file.txt'
    assert called['ref'] == 'branch'


def test_load_body_from_github_url_without_ref(monkeypatch):
    called = {}

    async def fake_decode(full_name, path, ref=None):
        called['full_name'] = full_name
        called['path'] = path
        called['ref'] = ref
        return {'decoded_bytes': b'github-no-ref', 'sha': 'sha'}

    monkeypatch.setattr('github_mcp.github_content._decode_github_content', fake_decode)

    result = asyncio.run(
        _load_body_from_content_url(
            'github:owner/repo:another/file.txt',
            context='github-test',
        )
    )

    assert result == b'github-no-ref'
    assert called['full_name'] == 'owner/repo'
    assert called['path'] == 'another/file.txt'
    assert called['ref'] is None


def test_load_body_from_github_url_invalid_spec():
    with pytest.raises(GitHubAPIError):
        asyncio.run(
            _load_body_from_content_url(
                'github:owner-repo-no-slash',
                context='github-test',
            )
        )
