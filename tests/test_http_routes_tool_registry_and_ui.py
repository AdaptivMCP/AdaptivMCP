from __future__ import annotations

from starlette.testclient import TestClient

import main


def test_resources_endpoint_returns_resources_only() -> None:
    client = TestClient(main.app)
    resp = client.get("/resources")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("finite") is True
    assert "resources" in payload
    # /resources is intended to be a resource catalog (not a tool catalog).
    assert "tools" not in payload


def test_tools_endpoint_includes_tools_and_resources() -> None:
    client = TestClient(main.app)
    resp = client.get("/tools")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("finite") is True
    assert isinstance(payload.get("tools"), list)
    assert isinstance(payload.get("resources"), list)


def test_ui_routes_exist() -> None:
    client = TestClient(main.app)

    resp = client.get("/ui.json")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload.get("endpoints", {}).get("health") == "/healthz"

    # Root and /ui should return HTML when assets are present.
    root = client.get("/")
    assert root.status_code in {200, 404}
    if root.status_code == 200:
        assert "text/html" in root.headers.get("content-type", "")
