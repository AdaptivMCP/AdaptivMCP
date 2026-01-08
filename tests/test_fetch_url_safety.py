import pytest


def _import_querying():
    # Import lazily so the test module can be collected even if optional
    # dependencies change.
    from github_mcp.main_tools import querying

    return querying


def test_validate_external_url_blocks_non_http_schemes(monkeypatch):
    querying = _import_querying()

    ok, reason = querying._validate_external_url("file:///etc/passwd")
    assert ok is False
    assert "http/https" in reason.lower()


def test_validate_external_url_blocks_localhost(monkeypatch):
    querying = _import_querying()

    ok, reason = querying._validate_external_url("http://localhost:8000")
    assert ok is False
    assert "localhost" in reason.lower()


def test_validate_external_url_blocks_private_ip_literal(monkeypatch):
    querying = _import_querying()

    ok, reason = querying._validate_external_url("http://10.0.0.1")
    assert ok is False
    assert "ip" in reason.lower()


def test_validate_external_url_blocks_dns_to_private_ip(monkeypatch):
    querying = _import_querying()

    def fake_getaddrinfo(host, port, type=None):  # noqa: A002
        assert host == "example.test"
        return [(querying.socket.AF_INET, None, None, None, ("192.168.1.2", port))]

    monkeypatch.setattr(querying.socket, "getaddrinfo", fake_getaddrinfo)

    ok, reason = querying._validate_external_url("https://example.test/path")
    assert ok is False
    assert "resolved" in reason.lower() or "ip" in reason.lower()


@pytest.mark.asyncio
async def test_fetch_url_caps_content(monkeypatch):
    querying = _import_querying()

    # Ensure the test uses the in-module defaults rather than any entry-module
    # override that may be present when importing the full app.
    def _resolve(_name, default):
        return default

    monkeypatch.setattr(querying, "_resolve_main_helper", _resolve)

    monkeypatch.setenv("MCP_FETCH_URL_MAX_BYTES", "5")
    monkeypatch.setenv("MCP_FETCH_URL_TIMEOUT_SECONDS", "1")

    # Keep DNS resolution deterministic and globally routable for this test.
    def fake_getaddrinfo(host, port, type=None):  # noqa: A002
        assert host == "example.test"
        return [(querying.socket.AF_INET, None, None, None, ("93.184.216.34", port))]

    monkeypatch.setattr(querying.socket, "getaddrinfo", fake_getaddrinfo)

    class _FakeResp:
        status_code = 200
        headers = {"Content-Type": "text/plain"}
        encoding = "utf-8"

        async def aiter_bytes(self):
            yield b"hello"
            yield b"world"

    class _FakeStream:
        async def __aenter__(self):
            return _FakeResp()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _FakeClient:
        def stream(self, method, url, timeout=None):
            assert method == "GET"
            assert url == "https://example.test/"
            return _FakeStream()

    class _DummySem:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        querying, "_default_external_client_instance", lambda: _FakeClient()
    )
    monkeypatch.setattr(
        querying, "_default_get_concurrency_semaphore", lambda: _DummySem()
    )
    monkeypatch.setattr(
        querying,
        "_default_structured_tool_error",
        lambda e, **_: {"status": "error", "message": str(e)},
    )
    monkeypatch.setattr(
        querying, "_default_sanitize_response_headers", lambda h: dict(h)
    )

    result = await querying.fetch_url("https://example.test/")
    assert result["status_code"] == 200
    assert result["content"] == "hello"
    assert result["content_truncated"] is True
    assert result["max_bytes"] == 5
