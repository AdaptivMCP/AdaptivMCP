from __future__ import annotations

import asyncio
from typing import Any

from starlette.testclient import TestClient

import main


def test_invoke_endpoint_maps_structured_error_status(monkeypatch: Any) -> None:
    """Tool wrappers may return raw error payloads instead of raising."""

    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "fake_tool"
        write_action = False

    def func(**_kwargs: Any) -> dict[str, Any]:
        return {"error": "bad args"}

    monkeypatch.setattr(tool_registry, "_find_registered_tool", lambda _name: (Tool(), func))

    client = TestClient(main.app)
    resp = client.post("/tools/fake_tool", json={"args": {"x": 1}})
    assert resp.status_code == 500
    payload = resp.json()
    assert payload.get("error") == "bad args"


def test_invoke_endpoint_retries_retryable_structured_errors(monkeypatch: Any) -> None:
    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "flaky_tool"
        write_action = False

    calls = {"n": 0}

    def func(**_kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        return {"error": "upstream"}

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(tool_registry, "_find_registered_tool", lambda _name: (Tool(), func))
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = TestClient(main.app)
    resp = client.post("/tools/flaky_tool", json={"args": {}}, params={"max_attempts": 2})
    assert resp.status_code == 500
    assert resp.json().get("error") == "upstream"
    assert calls["n"] == 1


def test_invoke_endpoint_does_not_retry_write_tools(monkeypatch: Any) -> None:
    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "writey"
        write_action = True

    calls = {"n": 0}

    def func(**_kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        return {"error": "rate limited"}

    async def fake_sleep(_seconds: float) -> None:
        raise AssertionError("sleep should not be called for write tools")

    monkeypatch.setattr(tool_registry, "_find_registered_tool", lambda _name: (Tool(), func))
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = TestClient(main.app)
    resp = client.post("/tools/writey", json={"args": {}}, params={"max_attempts": 3})
    assert resp.status_code == 500
    assert calls["n"] == 1
