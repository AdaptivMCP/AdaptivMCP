from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_render_request_requires_auth_by_default(monkeypatch):
    from github_mcp.exceptions import RenderAuthError
    from github_mcp.render_api import render_request

    for name in ("RENDER_API_KEY", "RENDER_API_TOKEN", "RENDER_TOKEN"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RenderAuthError):
        await render_request("GET", "/v1/owners")


@pytest.mark.asyncio
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

    payload = await render_request("GET", "/v1/owners")
    assert payload["status_code"] == 200
    assert payload["json"] == {"ok": True}
