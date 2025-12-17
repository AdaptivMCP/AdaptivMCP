import importlib

from starlette.testclient import TestClient

import main


def _client() -> TestClient:
    importlib.reload(main)
    return TestClient(main.app)


def test_static_assets_are_cacheable():
    client = _client()
    resp = client.get("/static/logo/adaptiv-icon-128.png")
    # StaticFiles with check_dir=False will 404 if missing; ensure repo ships the asset.
    assert resp.status_code == 200
    cache_control = resp.headers.get("Cache-Control", "")
    assert "max-age=31536000" in cache_control
    assert "immutable" in cache_control


def test_dynamic_endpoints_are_no_store(monkeypatch):
    # Use /healthz as a representative dynamic endpoint.
    monkeypatch.setenv("GITHUB_PAT", "token")
    client = _client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert "no-store" in resp.headers.get("Cache-Control", "")
