from __future__ import annotations

from starlette.testclient import TestClient

import main


def test_render_owners_invalid_limit_returns_400(monkeypatch) -> None:
    async def _owners(cursor=None, limit: int = 20):
        raise AssertionError("tool should not be called when parsing fails")

    monkeypatch.setattr("github_mcp.main_tools.render.list_render_owners", _owners)

    client = TestClient(main.app)
    resp = client.get("/render/owners?limit=abc")
    assert resp.status_code == 400
    payload = resp.json()
    detail = payload.get("error_detail") or {}
    assert detail.get("category") == "validation"


def test_render_services_invalid_limit_returns_400(monkeypatch) -> None:
    async def _services(owner_id=None, cursor=None, limit: int = 20):
        raise AssertionError("tool should not be called when parsing fails")

    monkeypatch.setattr("github_mcp.main_tools.render.list_render_services", _services)

    client = TestClient(main.app)
    resp = client.get("/render/services?limit=notanint")
    assert resp.status_code == 400
    payload = resp.json()
    detail = payload.get("error_detail") or {}
    assert detail.get("category") == "validation"


def test_render_deploys_invalid_limit_returns_400(monkeypatch) -> None:
    async def _deploys(service_id: str, cursor=None, limit: int = 20):
        raise AssertionError("tool should not be called when parsing fails")

    monkeypatch.setattr("github_mcp.main_tools.render.list_render_deploys", _deploys)

    client = TestClient(main.app)
    resp = client.get("/render/services/svc123/deploys?limit=oops")
    assert resp.status_code == 400
    payload = resp.json()
    detail = payload.get("error_detail") or {}
    assert detail.get("category") == "validation"


def test_render_deploy_create_invalid_json_body_defaults(monkeypatch) -> None:
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
    resp = client.post("/render/services/svc123/deploys", data="not-json")
    assert resp.status_code == 200
    assert resp.json()["json"]["deploy"] == "d1"
    assert observed["service_id"] == "svc123"
    assert observed["clear_cache"] is False
    assert observed["commit_id"] is None
    assert observed["image_url"] is None


def test_render_logs_requires_owner_and_resources() -> None:
    client = TestClient(main.app)
    resp = client.get("/render/logs")
    assert resp.status_code == 400
    detail = (resp.json().get("error_detail") or {}).get("category")
    assert detail == "validation"


def test_render_logs_resources_parsing_comma_separated(monkeypatch) -> None:
    observed = {}

    async def _logs(owner_id: str, resources: list[str], **kwargs):
        observed.update({"owner_id": owner_id, "resources": resources, "kwargs": kwargs})
        return {"status_code": 200, "json": {"lines": []}, "headers": {}}

    monkeypatch.setattr("github_mcp.main_tools.render.list_render_logs", _logs)

    client = TestClient(main.app)
    resp = client.get("/render/logs?owner_id=o1&resources=r1,%20r2&limit=2")
    assert resp.status_code == 200
    assert observed["owner_id"] == "o1"
    assert observed["resources"] == ["r1", "r2"]
    assert observed["kwargs"]["limit"] == 2


def test_render_logs_resources_parsing_repeated_params(monkeypatch) -> None:
    observed = {}

    async def _logs(owner_id: str, resources: list[str], **kwargs):
        observed.update({"owner_id": owner_id, "resources": resources, "kwargs": kwargs})
        return {"status_code": 200, "json": {"lines": []}, "headers": {}}

    monkeypatch.setattr("github_mcp.main_tools.render.list_render_logs", _logs)

    client = TestClient(main.app)
    resp = client.get("/render/logs?owner_id=o1&resources=r1&resources=r2")
    assert resp.status_code == 200
    assert observed["resources"] == ["r1", "r2"]


def test_render_logs_invalid_status_code_returns_400() -> None:
    client = TestClient(main.app)
    resp = client.get("/render/logs?owner_id=o1&resources=r1&status_code=bad")
    assert resp.status_code == 400
    payload = resp.json()
    detail = payload.get("error_detail") or {}
    assert detail.get("category") == "validation"

