from __future__ import annotations

import sys
import types
from collections.abc import AsyncIterator

import pytest

from github_mcp.main_tools import querying


class _DummyAsyncCM:
    def __init__(self, obj):
        self._obj = obj

    async def __aenter__(self):
        return self._obj

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummySemaphore:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.anyio
async def test_search_validations_use_structured_error(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def github_request(*args, **kwargs):  # pragma: no cover
        raise AssertionError("github_request should not be called")

    def structured_tool_error(exc: Exception, *, context: str, **kwargs):
        calls.append((context, exc.__class__.__name__))
        return {
            "status": "error",
            "context": context,
            "error_type": exc.__class__.__name__,
        }

    mod = types.SimpleNamespace(
        _github_request=github_request, _structured_tool_error=structured_tool_error
    )
    monkeypatch.setitem(sys.modules, "main", mod)

    res = await querying.search("q", search_type="bad")
    assert res["status"] == "error"
    assert calls[-1][0] == "search"

    res = await querying.search("q", per_page=0)
    assert res["status"] == "error"

    res = await querying.search("q", page=0)
    assert res["status"] == "error"

    res = await querying.search("q", per_page=101)
    assert res["status"] == "error"

    res = await querying.search("q", per_page=10, page=200)
    assert res["status"] == "error"

    res = await querying.search("q", order="nope")
    assert res["status"] == "error"


@pytest.mark.anyio
async def test_search_commits_sets_accept_header(monkeypatch):
    seen: dict[str, object] = {}

    async def github_request(method, path, *, params=None, headers=None, **kwargs):
        seen["method"] = method
        seen["path"] = path
        seen["params"] = params
        seen["headers"] = headers
        return {"status": "ok"}

    def structured_tool_error(exc: Exception, *, context: str, **kwargs):
        raise AssertionError(f"structured_tool_error should not be called: {exc}")

    mod = types.SimpleNamespace(
        _github_request=github_request, _structured_tool_error=structured_tool_error
    )
    # querying._resolve_main_helper checks `main` first.
    monkeypatch.setitem(sys.modules, "main", mod)

    res = await querying.search("q", search_type="commits", per_page=5, page=1)
    assert res == {"status": "ok"}
    assert seen["path"] == "/search/commits"
    assert isinstance(seen["headers"], dict)
    assert "application/vnd.github" in str(seen["headers"].get("Accept"))


@pytest.mark.anyio
async def test_graphql_query_returns_json_dict(monkeypatch):
    async def github_request(method, path, *, json_body=None, **kwargs):
        assert method == "POST"
        assert path == "/graphql"
        assert "query" in (json_body or {})
        return {"json": {"data": {"ok": True}}}

    def structured_tool_error(exc: Exception, *, context: str, **kwargs):
        raise AssertionError("should not error")

    mod = types.SimpleNamespace(
        _github_request=github_request, _structured_tool_error=structured_tool_error
    )
    monkeypatch.setitem(sys.modules, "main", mod)

    res = await querying.graphql_query("query { viewer { login } }")
    assert res == {"data": {"ok": True}}


@pytest.mark.anyio
async def test_graphql_query_missing_json_returns_structured_error(monkeypatch):
    async def github_request(*args, **kwargs):
        return {"json": "not-a-dict"}

    def structured_tool_error(exc: Exception, *, context: str, **kwargs):
        return {
            "status": "error",
            "context": context,
            "error_type": exc.__class__.__name__,
        }

    mod = types.SimpleNamespace(
        _github_request=github_request, _structured_tool_error=structured_tool_error
    )
    monkeypatch.setitem(sys.modules, "main", mod)

    res = await querying.graphql_query("query { x }")
    assert res["status"] == "error"
    assert res["context"] == "graphql_query"


@pytest.mark.anyio
async def test_fetch_url_filters_headers_and_sets_content_type(monkeypatch):
    class DummyResp:
        status_code = 200
        headers = {"Content-Type": "text/plain", "X-Ignore": "nope"}

        async def aiter_bytes(self) -> AsyncIterator[bytes]:
            yield b"hello"

    class DummyClient:
        def stream(self, method, url):
            assert method == "GET"
            assert url == "https://example.com"
            return _DummyAsyncCM(DummyResp())

    def external_client_instance():
        return DummyClient()

    def get_concurrency_semaphore():
        return _DummySemaphore()

    def structured_tool_error(exc: Exception, *, context: str, **kwargs):
        raise AssertionError(f"unexpected error: {exc}")

    mod = types.SimpleNamespace(
        _external_client_instance=external_client_instance,
        _get_concurrency_semaphore=get_concurrency_semaphore,
        _structured_tool_error=structured_tool_error,
    )
    monkeypatch.setitem(sys.modules, "main", mod)

    res = await querying.fetch_url("https://example.com")
    assert res["status_code"] == 200
    assert res["headers"].get("content-type") == "text/plain"
    assert res["content_type"] == "text/plain"
    assert res["size_bytes"] == 5
    assert res["content"] == "hello"


@pytest.mark.anyio
async def test_fetch_url_exception_returns_structured_error(monkeypatch):
    class DummyClient:
        def stream(self, method, url):
            raise RuntimeError("boom")

    def external_client_instance():
        return DummyClient()

    def get_concurrency_semaphore():
        return _DummySemaphore()

    def structured_tool_error(exc: Exception, *, context: str, **kwargs):
        return {"status": "error", "context": context, "path": kwargs.get("path")}

    mod = types.SimpleNamespace(
        _external_client_instance=external_client_instance,
        _get_concurrency_semaphore=get_concurrency_semaphore,
        _structured_tool_error=structured_tool_error,
    )
    # querying._resolve_main_helper checks `main` first.
    monkeypatch.setitem(sys.modules, "main", mod)

    res = await querying.fetch_url("https://example.com")
    assert res["status"] == "error"
    assert res["context"] == "fetch_url"
    assert res["path"] == "https://example.com"
