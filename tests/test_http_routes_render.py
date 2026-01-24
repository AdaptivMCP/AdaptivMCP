from __future__ import annotations

from starlette.testclient import TestClient

import main


def test_render_owners_route_success(monkeypatch) -> None:
    async def _owners(cursor=None, limit: int = 20):
        assert limit == 10
        assert cursor == "abc"
        return {"status_code": 200, "json": {"owners": ["o1"]}, "headers": {}}

    monkeypatch.setattr("github_mcp.main_tools.render.list_render_owners", _owners)

    client = TestClient(main.app)
    resp = client.get("/render/owners?cursor=abc&limit=10")
    assert resp.status_code == 200
    assert resp.json()["json"]["owners"] == ["o1"]


def test_render_deploy_create_route_success(monkeypatch) -> None:
    observed = {}

    async def _create(
        service_id: str, clear_cache: bool = False, commit_id=None, image_url=None
    ):
        observed.update(
            {
                "service_id": service_id,
                "clear_cache": clear_cache,
                "commit_id": commit_id,
                "image_url": image_url,
            }
        )
        return {"status_code": 201, "json": {"deploy": "d1"}, "headers": {}}

    monkeypatch.setattr("github_mcp.main_tools.render.create_render_deploy", _create)

    client = TestClient(main.app)
    resp = client.post(
        "/render/services/svc123/deploys",
        json={"clear_cache": True, "commit_id": "deadbeef"},
    )
    assert resp.status_code == 200
    assert resp.json()["json"] == {"deploy": "d1"}
    assert observed["service_id"] == "svc123"
    assert observed["clear_cache"] is True
    assert observed["commit_id"] == "deadbeef"
    assert observed["image_url"] is None


def test_render_routes_translate_auth_error_to_401(monkeypatch) -> None:
    from github_mcp.exceptions import RenderAuthError

    async def _owners(cursor=None, limit: int = 20):
        raise RenderAuthError("missing token")

    monkeypatch.setattr("github_mcp.main_tools.render.list_render_owners", _owners)

    client = TestClient(main.app)
    resp = client.get("/render/owners")
    assert resp.status_code == 401
    payload = resp.json()
    assert payload.get("error")
    detail = payload.get("error_detail") or {}
    assert detail.get("category") == "auth"
