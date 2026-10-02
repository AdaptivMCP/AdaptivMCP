from __future__ import annotations

import pytest


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
async def test_load_body_from_content_url_github_bytearray(monkeypatch):
    from github_mcp import github_content

    async def _fake_decode(*, full_name: str, path: str, ref: str | None = None):
        return {"decoded_bytes": bytearray(b"abc")}

    monkeypatch.setattr(github_content, "_decode_github_content", _fake_decode)

    body = await github_content._load_body_from_content_url(
        "github:owner/repo:path/to/file.txt",
        context="test",
    )
    assert body == b"abc"


@pytest.mark.asyncio
async def test_load_body_from_content_url_github_non_bytes_raises(monkeypatch):
    from github_mcp import github_content
    from github_mcp.exceptions import GitHubAPIError

    async def _fake_decode(*_args, **_kwargs):
        return {"decoded_bytes": "not-bytes"}

    monkeypatch.setattr(github_content, "_decode_github_content", _fake_decode)

    with pytest.raises(GitHubAPIError):
        await github_content._load_body_from_content_url(
            "github:owner/repo:path/to/file.txt",
            context="test",
        )


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
async def test_load_body_from_content_url_reads_local_file(tmp_path, monkeypatch):
    from github_mcp.github_content import _load_body_from_content_url

    f = tmp_path / "payload.bin"
    f.write_bytes(b"abc123")
    monkeypatch.setenv("ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS", str(tmp_path))

    body = await _load_body_from_content_url(str(f), context="test")
    assert body == b"abc123"


@pytest.mark.asyncio
async def test_load_body_from_content_url_rejects_local_file_by_default(tmp_path, monkeypatch):
    from github_mcp.github_content import _load_body_from_content_url
    from github_mcp.exceptions import GitHubAPIError

    f = tmp_path / "secret.txt"
    f.write_text("secret")
    monkeypatch.delenv("ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS", raising=False)

    with pytest.raises(GitHubAPIError, match="local content_url reads are disabled"):
        await _load_body_from_content_url(str(f), context="test")


@pytest.mark.asyncio
async def test_load_body_from_content_url_rejects_local_file_outside_allowed_root(
    tmp_path, monkeypatch
):
    from github_mcp.github_content import _load_body_from_content_url
    from github_mcp.exceptions import GitHubAPIError

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    f = outside / "secret.txt"
    f.write_text("secret")
    monkeypatch.setenv("ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS", str(allowed))

    with pytest.raises(GitHubAPIError, match="outside the configured local content roots"):
        await _load_body_from_content_url(str(f), context="test")


@pytest.mark.asyncio
async def test_load_body_from_content_url_rejects_symlink_escape(tmp_path, monkeypatch):
    from github_mcp.github_content import _load_body_from_content_url
    from github_mcp.exceptions import GitHubAPIError

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("secret")
    link = allowed / "link.txt"
    link.symlink_to(secret)

    monkeypatch.setenv("ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS", str(allowed))

    with pytest.raises(GitHubAPIError, match="outside the configured local content roots"):
        await _load_body_from_content_url(str(link), context="test")



@pytest.mark.asyncio
async def test_load_body_from_content_url_http_error(monkeypatch):
    from github_mcp import github_content
    from github_mcp.exceptions import GitHubAPIError

    class _FakeResponse:
        status_code = 404
        content = b"nope"

    class _FakeClient:
        async def get(self, _url: str, **_kwargs):
            return _FakeResponse()

    monkeypatch.setenv("ADAPTIV_MCP_ALLOWED_CONTENT_HOSTS", "example.com")
    monkeypatch.setattr(github_content, "_external_client_instance", _FakeClient)

    with pytest.raises(GitHubAPIError):
        await github_content._load_body_from_content_url(
            "https://example.com/file.txt",
            context="test",
        )


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


@pytest.mark.asyncio
async def test_load_body_from_content_url_rejects_unapproved_host(monkeypatch):
    from github_mcp import github_content
    from github_mcp.exceptions import GitHubAPIError

    client_called = False

    class _FakeClient:
        async def get(self, _url: str, **_kwargs):
            nonlocal client_called
            client_called = True
            raise AssertionError("network client must not be called")

    monkeypatch.setattr(github_content, "_external_client_instance", _FakeClient)

    with pytest.raises(GitHubAPIError, match="host is not allowed"):
        await github_content._load_body_from_content_url(
            "https://attacker.example/file.txt", context="test"
        )
    assert client_called is False


@pytest.mark.asyncio
async def test_load_body_from_content_url_rejects_private_dns_result(monkeypatch):
    from github_mcp import github_content
    from github_mcp.exceptions import GitHubAPIError

    monkeypatch.setenv("ADAPTIV_MCP_ALLOWED_CONTENT_HOSTS", "example.com")
    monkeypatch.setattr(
        github_content.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )

    with pytest.raises(GitHubAPIError, match="non-public IP"):
        await github_content._load_body_from_content_url(
            "https://example.com/file.txt", context="test"
        )


@pytest.mark.asyncio
async def test_load_body_from_content_url_disables_redirects(monkeypatch):
    from github_mcp import github_content

    monkeypatch.setenv("ADAPTIV_MCP_ALLOWED_CONTENT_HOSTS", "example.com")

    class _FakeResponse:
        status_code = 200
        content = b"ok"

    calls = []

    class _FakeClient:
        async def get(self, url: str, **kwargs):
            calls.append((url, kwargs))
            return _FakeResponse()

    monkeypatch.setattr(
        github_content.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr(github_content, "_external_client_instance", _FakeClient)

    body = await github_content._load_body_from_content_url(
        "https://example.com/file.txt", context="test"
    )
    assert body == b"ok"
    assert calls == [
        ("https://example.com/file.txt", {"follow_redirects": False})
    ]


@pytest.mark.asyncio
async def test_load_body_from_content_url_rejects_shared_address_range(monkeypatch):
    from github_mcp import github_content
    from github_mcp.exceptions import GitHubAPIError

    monkeypatch.setenv("ADAPTIV_MCP_ALLOWED_CONTENT_HOSTS", "example.com")
    monkeypatch.setattr(
        github_content.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (2, 1, 6, "", ("100.64.0.1", 443)),
        ],
    )

    with pytest.raises(GitHubAPIError, match="non-public IP"):
        await github_content._load_body_from_content_url(
            "https://example.com/file.txt", context="test"
        )


@pytest.mark.asyncio
async def test_load_body_from_content_url_preserves_local_policy_error(
    tmp_path, monkeypatch
):
    from github_mcp.github_content import _load_body_from_content_url
    from github_mcp.exceptions import GitHubAPIError

    f = tmp_path / "secret.txt"
    f.write_text("secret")
    monkeypatch.setenv(
        "ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS", str(tmp_path / "other")
    )

    with pytest.raises(
        GitHubAPIError, match="outside the configured local content roots"
    ):
        await _load_body_from_content_url(str(f), context="test")


@pytest.mark.asyncio
async def test_load_body_from_content_url_allows_filesystem_root(monkeypatch, tmp_path):
    from github_mcp.github_content import _load_body_from_content_url

    if __import__("os").name != "posix":
        pytest.skip("Filesystem-root semantics in this regression are POSIX-specific")

    f = tmp_path / "payload.bin"
    f.write_bytes(b"root-ok")
    monkeypatch.setenv("ADAPTIV_MCP_ALLOWED_LOCAL_CONTENT_ROOTS", "/")

    body = await _load_body_from_content_url(str(f), context="test")
    assert body == b"root-ok"
