from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_render_request_requires_auth_by_default(monkeypatch):
    from github_mcp.exceptions import RenderAuthError
    from github_mcp.render_api import render_request

    for name in ("RENDER_API_KEY", "RENDER_API_TOKEN", "RENDER_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RenderAuthError):
        await render_request("GET", "/owners")


@pytest.mark.anyio
async def test_render_request_success_payload(monkeypatch):
    import httpx

    from github_mcp.render_api import render_request

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    class DummyClient:
        async def request(self, method, url, params=None, json=None, headers=None):
            req = httpx.Request(method, f"https://api.render.com{url}")
            return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(
        "github_mcp.render_api._render_client_instance",
        lambda: DummyClient(),
    )

    payload = await render_request("GET", "/owners")
    assert payload["status_code"] == 200
    assert payload["json"] == {"ok": True}


@pytest.mark.anyio
async def test_render_request_auto_applies_v1_prefix(monkeypatch):
    import httpx

    import github_mcp.render_api as render_api

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    observed = {}

    class DummyClient:
        async def request(self, method, url, params=None, json=None, headers=None):
            observed["url"] = url
            req = httpx.Request(method, f"https://api.render.com{url}")
            return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(render_api, "RENDER_API_BASE", "https://api.render.com")
    monkeypatch.setattr(render_api, "_render_client_instance", lambda: DummyClient())
    monkeypatch.setattr(render_api, "_render_api_version_prefix", "/v1")

    await render_api.render_request("GET", "/owners")
    assert observed.get("url") == "/v1/owners"


@pytest.mark.anyio
async def test_render_request_does_not_double_prefix(monkeypatch):
    import httpx

    import github_mcp.render_api as render_api

    monkeypatch.setenv("RENDER_API_KEY", "test-token")

    observed = {}

    class DummyClient:
        async def request(self, method, url, params=None, json=None, headers=None):
            observed["url"] = url
            req = httpx.Request(method, f"https://api.render.com{url}")
            return httpx.Response(200, json={"ok": True}, request=req)

    monkeypatch.setattr(render_api, "RENDER_API_BASE", "https://api.render.com/v1")
    monkeypatch.setattr(render_api, "_render_client_instance", lambda: DummyClient())
    monkeypatch.setattr(render_api, "_render_api_version_prefix", "/v1")

    await render_api.render_request("GET", "/v1/owners")
    assert observed.get("url") == "/v1/owners"
