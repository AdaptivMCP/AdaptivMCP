import asyncio
import sys
import types
import weakref

import httpx
import pytest

from github_mcp import http_clients
from github_mcp.config import MAX_CONCURRENCY
from github_mcp.exceptions import GitHubAPIError, GitHubAuthError


def test_get_github_token_variants(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)
    with pytest.raises(GitHubAuthError):
        http_clients._get_github_token()

    monkeypatch.setenv("GITHUB_TOKEN", "  abc123  ")
    assert http_clients._get_github_token() == "abc123"

    monkeypatch.setenv("GITHUB_PAT", "   ")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(GitHubAuthError):
        http_clients._get_github_token()


def test_concurrency_semaphore_is_per_loop(monkeypatch):
    monkeypatch.setattr(http_clients, "_loop_semaphores", weakref.WeakKeyDictionary())

    try:
        original_loop = asyncio.get_event_loop_policy().get_event_loop()
        created_original = False
    except RuntimeError:
        original_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(original_loop)
        created_original = True
    loop_one = asyncio.new_event_loop()
    loop_two = asyncio.new_event_loop()

    async def capture():
        return http_clients._get_concurrency_semaphore()

    try:
        asyncio.set_event_loop(loop_one)
        first = loop_one.run_until_complete(capture())
        again = loop_one.run_until_complete(capture())

        asyncio.set_event_loop(loop_two)
        second = loop_two.run_until_complete(capture())
    finally:
        asyncio.set_event_loop(original_loop)
        loop_one.close()
        loop_two.close()
        if created_original:
            original_loop.close()

    assert first is again
    assert first is not second
    assert first._value == MAX_CONCURRENCY
    assert second._value == MAX_CONCURRENCY


def test_github_client_instance_uses_token_header(monkeypatch):
    monkeypatch.setattr(http_clients, "_http_client_github", None)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")

    client = http_clients._github_client_instance()
    try:
        assert client.headers.get("Authorization") == "Bearer secret-token"
    finally:
        asyncio.run(client.aclose())
        monkeypatch.setattr(http_clients, "_http_client_github", None)


def test_github_client_instance_without_token(monkeypatch):
    monkeypatch.setattr(http_clients, "_http_client_github", None)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_PAT", raising=False)

    client = http_clients._github_client_instance()
    try:
        assert "Authorization" not in client.headers
    finally:
        asyncio.run(client.aclose())
        monkeypatch.setattr(http_clients, "_http_client_github", None)


def test_external_client_instance_prefers_main_patch(monkeypatch):
    monkeypatch.setattr(http_clients, "_http_client_external", None)
    sentinel_client = object()

    fake_main = types.SimpleNamespace(_http_client_external=sentinel_client)
    monkeypatch.setitem(sys.modules, "main", fake_main)

    assert http_clients._external_client_instance() is sentinel_client
    monkeypatch.setattr(http_clients, "_http_client_external", None)


def test_request_with_metrics_records_and_returns_response(monkeypatch):
    records = []

    def fake_record(**kwargs):
        records.append(kwargs)

    class DummyClient:
        def __init__(self):
            self.closed = False

        def request(self, method, url, **kwargs):
            return httpx.Response(200, text="ok")

        def close(self):
            self.closed = True

    monkeypatch.setattr(http_clients, "_record_github_request", fake_record)

    client = DummyClient()
    response = http_clients._request_with_metrics(
        "GET", "https://example.com", client_factory=lambda: client
    )

    assert response.status_code == 200
    assert records and records[0]["status_code"] == 200
    assert records[0]["error"] is False
    assert client.closed is True


def test_request_with_metrics_auth_error(monkeypatch):
    records = []

    def fake_record(**kwargs):
        records.append(kwargs)

    monkeypatch.setattr(http_clients, "_record_github_request", fake_record)

    def failing_factory():
        raise GitHubAuthError("boom")

    with pytest.raises(GitHubAuthError):
        http_clients._request_with_metrics(
            "GET", "https://example.com", client_factory=failing_factory
        )

    assert records and records[0]["status_code"] is None
    assert records[0]["error"] is True


def test_request_with_metrics_raises_for_http_error(monkeypatch):
    records = []

    def fake_record(**kwargs):
        records.append(kwargs)

    class DummyClient:
        def __init__(self, status):
            self.status = status
            self.closed = False

        def request(self, method, url, **kwargs):
            return httpx.Response(self.status, text="fail")

        def close(self):
            self.closed = True

    monkeypatch.setattr(http_clients, "_record_github_request", fake_record)

    client = DummyClient(status=401)
    with pytest.raises(GitHubAuthError):
        http_clients._request_with_metrics(
            "GET", "https://example.com", client_factory=lambda: client
        )

    assert client.closed is True
    assert records[-1]["error"] is True

    client = DummyClient(status=500)
    with pytest.raises(GitHubAPIError):
        http_clients._request_with_metrics(
            "GET", "https://example.com", client_factory=lambda: client
        )

    assert records[-1]["status_code"] == 500
    assert records[-1]["error"] is True
