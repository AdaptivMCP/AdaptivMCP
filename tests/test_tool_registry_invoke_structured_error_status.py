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

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post("/tools/fake_tool", json={"args": {"x": 1}})
    # "bad args" is treated as a validation error.
    assert resp.status_code == 400
    payload = resp.json()
    assert payload.get("status") == "error"
    assert payload.get("ok") is False
    assert payload.get("error") == "bad args"
    assert payload.get("error_detail", {}).get("category") == "validation"
    assert payload.get("error_detail", {}).get("message") == "bad args"


def test_invoke_endpoint_wraps_bare_error_detail(monkeypatch: Any) -> None:
    """Legacy tools may return the error_detail dict directly."""

    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "detail_only"
        write_action = False

    def func(**_kwargs: Any) -> dict[str, Any]:
        return {"category": "validation", "message": "missing required arg"}

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post("/tools/detail_only", json={"args": {}})
    assert resp.status_code == 400
    payload = resp.json()
    assert payload.get("status") == "error"
    assert payload.get("ok") is False
    assert payload.get("error") == "missing required arg"
    assert payload.get("error_detail", {}).get("category") == "validation"


def test_invoke_endpoint_does_not_double_wrap_error_envelopes(monkeypatch: Any) -> None:
    """If a tool returns an error envelope without error_detail, normalize safely."""

    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "enveloped"
        write_action = False

    def func(**_kwargs: Any) -> dict[str, Any]:
        # Older wrappers sometimes return an envelope-ish payload without
        # embedding the detail dict.
        return {
            "status": "error",
            "ok": False,
            "category": "validation",
            "error": "bad args",
            "hint": "use {args: {...}}",
        }

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post("/tools/enveloped", json={"args": {"x": 1}})
    assert resp.status_code == 400
    payload = resp.json()
    assert payload.get("status") == "error"
    assert payload.get("ok") is False
    assert payload.get("error") == "bad args"

    detail = payload.get("error_detail")
    assert isinstance(detail, dict)
    assert detail.get("category") == "validation"
    assert detail.get("message") == "bad args"
    assert detail.get("hint") == "use {args: {...}}"

    # Crucially: do not nest the whole envelope inside error_detail.
    assert "status" not in detail
    assert "ok" not in detail


def test_invoke_endpoint_maps_uppercase_rate_limit_codes(monkeypatch: Any) -> None:
    """Error code mapping should be case-insensitive."""

    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "ratey"
        write_action = False

    def func(**_kwargs: Any) -> dict[str, Any]:
        return {
            "error_detail": {"code": "GITHUB_RATE_LIMITED", "message": "rate limited"}
        }

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post("/tools/ratey", json={"args": {}})
    assert resp.status_code == 429


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

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = TestClient(main.app)
    resp = client.post(
        "/tools/flaky_tool", json={"args": {}}, params={"max_attempts": 2}
    )
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

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    client = TestClient(main.app)
    resp = client.post("/tools/writey", json={"args": {}}, params={"max_attempts": 3})
    assert resp.status_code == 429
    assert calls["n"] == 1


def test_invoke_endpoint_returns_200_for_openai_clients_on_structured_errors(
    monkeypatch: Any,
) -> None:
    """Hosted clients may treat non-2xx as a hard tool failure.

    For these clients we keep the structured error payload but return 200 and
    include the original status in a header.
    """

    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "bad_tool"
        write_action = False

    def func(**_kwargs: Any) -> dict[str, Any]:
        return {
            "error_detail": {
                "category": "validation",
                "message": "bad args",
            }
        }

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post(
        "/tools/bad_tool",
        json={"args": {"x": 1}},
        headers={"x-openai-assistant-id": "test"},
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Tool-Original-Status") == "400"
    payload = resp.json()
    assert payload.get("error") == "bad args"
    assert payload.get("error_detail", {}).get("message") == "bad args"
