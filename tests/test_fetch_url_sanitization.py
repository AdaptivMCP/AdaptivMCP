from __future__ import annotations

import asyncio
import types

import pytest


class _DummyStreamResponse:
    def __init__(self, *, status_code: int, headers: dict[str, str], body: bytes) -> None:
        self.status_code = status_code
        self.headers = headers
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_bytes(self):
        # Yield in chunks to simulate streaming.
        for i in range(0, len(self._body), 3):
            yield self._body[i : i + 3]


class _DummyExternalClient:
    def __init__(self, *, response: _DummyStreamResponse) -> None:
        self._response = response

    def stream(self, method: str, url: str):
        assert method == "GET"
        assert url.startswith("https://")
        return self._response


@pytest.mark.anyio
async def test_fetch_url_caps_and_sanitizes_headers(monkeypatch):
    import github_mcp.main_tools.querying as querying

    # Force small caps to ensure truncation paths are exercised.
    monkeypatch.setattr(querying, "GITHUB_MCP_MAX_FETCH_URL_BYTES", 5)
    monkeypatch.setattr(querying, "GITHUB_MCP_MAX_FETCH_URL_TEXT_CHARS", 10)

    body = b"hello world"  # 11 bytes
    resp = _DummyStreamResponse(
        status_code=200,
        headers={
            "Content-Type": "text/plain",
            "Set-Cookie": "secret=1",
            "Authorization": "Bearer secret",
            "ETag": "abc",
        },
        body=body,
    )
    client = _DummyExternalClient(response=resp)

    dummy_main = types.SimpleNamespace(
        _external_client_instance=lambda: client,
        _get_concurrency_semaphore=lambda: asyncio.Semaphore(1),
    )
    monkeypatch.setitem(__import__("sys").modules, "main", dummy_main)

    out = await querying.fetch_url("https://example.com")

    assert out["status_code"] == 200
    assert out["truncated"] is True
    assert out["size_bytes"] == 5

    # Only allowlisted headers are returned.
    headers = out["headers"]
    assert "ETag" in headers or "etag" in {k.lower() for k in headers}
    assert "set-cookie" not in {k.lower() for k in headers}
    assert "authorization" not in {k.lower() for k in headers}
