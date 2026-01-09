from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_fetch_url_blocks_non_http_scheme(monkeypatch):
    import github_mcp.main_tools.querying as querying

    result = await querying.fetch_url("file:///etc/passwd")
    assert result.get("error")


@pytest.mark.asyncio
async def test_fetch_url_blocks_localhost(monkeypatch):
    import github_mcp.main_tools.querying as querying

    result = await querying.fetch_url("http://localhost/")
    assert result.get("error")


@pytest.mark.asyncio
async def test_fetch_url_redacts_set_cookie(monkeypatch):
    import github_mcp.main_tools.querying as querying

    async def _noop_validate(_url: str):
        return None

    class _Resp:
        status_code = 200
        headers = {"Set-Cookie": "a=b", "Content-Type": "text/plain"}

        async def aiter_bytes(self):
            yield b"ok"

    class _StreamCtx:
        async def __aenter__(self):
            return _Resp()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Client:
        def stream(self, *args, **kwargs):
            return _StreamCtx()

    monkeypatch.setattr(querying, "_validate_fetch_url_target", _noop_validate)
    monkeypatch.setattr(querying, "_resolve_main_helper", lambda name, default: default)
    monkeypatch.setattr(querying, "_default_external_client_instance", lambda: _Client())
    monkeypatch.setattr(querying, "_default_get_concurrency_semaphore", lambda: _NullAsyncCtx())

    result = await querying.fetch_url("https://example.com")
    assert result["status_code"] == 200
    assert "Set-Cookie" not in result["headers"]
    assert result["content"] == "ok"


class _NullAsyncCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False
