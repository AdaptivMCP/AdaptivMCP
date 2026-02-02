from __future__ import annotations

import importlib

import pytest


@pytest.mark.anyio
async def test_render_request_logs_compact_by_default(monkeypatch):
    import httpx

    import github_mcp.render_api as render_api

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    calls: list[dict[str, object]] = []

    def capture(*, level: str, msg: str, extra: dict):
        calls.append({"level": level, "msg": msg, "extra": extra})

    monkeypatch.setattr(render_api, "LOG_RENDER_HTTP", True)
    monkeypatch.setattr(render_api, "LOG_RENDER_HTTP_DETAILS", False)
    monkeypatch.setattr(render_api, "LOG_RENDER_HTTP_BODIES", False)
    monkeypatch.setattr(render_api, "_log_render_http", capture)

    class DummyClient:
        async def request(self, method, url, params=None, json=None, headers=None):
            req = httpx.Request(method, f"https://api.render.com{url}")
            return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(render_api, "_render_client_instance", lambda: DummyClient())

    await render_api.render_request(
        "GET",
        "/owners",
        params={"a": 1},
        json_body={"x": "y"},
        headers={"X-Test": "1"},
    )

    assert calls, "expected at least one render log call"
    started = calls[0]
    assert "params=" not in str(started["msg"])
    assert "json=" not in str(started["msg"])
    assert "headers=" not in str(started["msg"])

    extra = started["extra"]
    assert extra.get("event") == "render_http_started"
    assert "params" not in extra
    assert "json_body" not in extra
    assert "headers" not in extra


@pytest.mark.anyio
async def test_render_request_logs_details_when_enabled(monkeypatch):
    import httpx

    import github_mcp.render_api as render_api

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    calls: list[dict[str, object]] = []

    def capture(*, level: str, msg: str, extra: dict):
        calls.append({"level": level, "msg": msg, "extra": extra})

    monkeypatch.setattr(render_api, "LOG_RENDER_HTTP", True)
    monkeypatch.setattr(render_api, "LOG_RENDER_HTTP_DETAILS", True)
    monkeypatch.setattr(render_api, "LOG_RENDER_HTTP_BODIES", False)
    monkeypatch.setattr(render_api, "_log_render_http", capture)

    class DummyClient:
        async def request(self, method, url, params=None, json=None, headers=None):
            req = httpx.Request(method, f"https://api.render.com{url}")
            return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(render_api, "_render_client_instance", lambda: DummyClient())

    await render_api.render_request(
        "POST",
        "/owners",
        params={"a": 1},
        json_body={"x": "y"},
        headers={"X-Test": "1"},
    )

    started = calls[0]
    assert "params=" in str(started["msg"])
    assert "json=" in str(started["msg"])
    assert "headers=" in str(started["msg"])

    extra = started["extra"]
    assert extra.get("params") == {"a": 1}
    assert extra.get("json_body") == {"x": "y"}
    assert extra.get("headers") == {"X-Test": "1"}


def test_render_runtime_defaults_keep_logs_compact(monkeypatch):
    import github_mcp.config as config

    # Simulate Render runtime and reload config to recompute defaults.
    monkeypatch.setenv("RENDER", "true")
    for name in (
        "LOG_TOOL_PAYLOADS",
        "LOG_APPEND_EXTRAS",
        "LOG_EXTRAS_MAX_LINES",
        "LOG_EXTRAS_MAX_CHARS",
        "LOG_RENDER_HTTP_DETAILS",
    ):
        monkeypatch.delenv(name, raising=False)

    reloaded = importlib.reload(config)
    try:
        assert reloaded.LOG_TOOL_PAYLOADS is False
        assert reloaded.LOG_APPEND_EXTRAS is False
        assert reloaded.LOG_EXTRAS_MAX_LINES == 2000
        assert reloaded.LOG_EXTRAS_MAX_CHARS == 200000
        assert reloaded.LOG_RENDER_HTTP_DETAILS is False
    finally:
        # Restore to non-Render environment for the rest of the suite.
        monkeypatch.delenv("RENDER", raising=False)
        importlib.reload(config)
