from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

TestClient = pytest.importorskip("starlette.testclient").TestClient

import main  # noqa: E402


def _wait_for_status(
    client: TestClient, invocation_id: str, target: str
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for _ in range(100):
        resp = client.get(f"/tool_invocations/{invocation_id}")
        payload = resp.json()
        if payload.get("status") == target:
            break
        time.sleep(0.01)
    return payload


def test_async_tool_invocation_completes(monkeypatch: Any) -> None:
    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "async_tool"
        write_action = False

    async def func(**kwargs: Any) -> dict[str, Any]:
        return {"ok": True, "echo": kwargs.get("value")}

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post(
        "/tools/async_tool/invocations", json={"args": {"value": "hello"}}
    )
    assert resp.status_code == 202

    invocation_id = resp.json()["invocation_id"]
    payload = _wait_for_status(client, invocation_id, "succeeded")

    assert payload["status"] == "succeeded"
    assert payload["result"]["ok"] is True
    assert payload["result"]["echo"] == "hello"


def test_async_tool_invocation_cancelled(monkeypatch: Any) -> None:
    import github_mcp.http_routes.tool_registry as tool_registry

    class Tool:
        name = "slow_tool"
        write_action = False

    started = threading.Event()
    cancelled = threading.Event()

    async def func(**_kwargs: Any) -> dict[str, Any]:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {"ok": True}

    monkeypatch.setattr(
        tool_registry, "_find_registered_tool", lambda _name: (Tool(), func)
    )

    client = TestClient(main.app)
    resp = client.post("/tools/slow_tool/invocations", json={"args": {}})
    assert resp.status_code == 202
    invocation_id = resp.json()["invocation_id"]

    assert started.wait(1.0), "tool did not start in time"

    cancel_resp = client.post(f"/tool_invocations/{invocation_id}/cancel")
    assert cancel_resp.status_code == 200

    payload = _wait_for_status(client, invocation_id, "cancelled")

    assert payload["status"] == "cancelled"
    assert payload["status_code"] == 499
    assert isinstance(payload.get("result"), dict)
    assert payload["result"]["status"] == "cancelled"
    assert cancelled.is_set()
