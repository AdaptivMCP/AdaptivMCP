from __future__ import annotations

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import main
from github_mcp.http_routes.session import register_session_routes


def _build_app():
    app = Starlette(routes=[Route("/", lambda _req: None, methods=["GET"])])
    register_session_routes(app)
    return main._RequestContextMiddleware(app)


def test_response_includes_server_anchor_header():
    client = TestClient(_build_app())
    resp = client.get("/session/ping")
    assert resp.status_code == 200
    assert resp.headers.get("x-server-anchor")
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["anchor"] == resp.headers["x-server-anchor"]


def test_session_anchor_and_assert_routes_roundtrip():
    client = TestClient(_build_app())
    anchor_resp = client.get("/session/anchor")
    assert anchor_resp.status_code == 200
    anchor = anchor_resp.json()["anchor"]
    assert isinstance(anchor, str) and len(anchor) >= 32

    ok = client.get(f"/session/assert?anchor={anchor}")
    assert ok.status_code == 200
    assert ok.json()["status"] == "anchor_match"

    bad = client.get("/session/assert?anchor=deadbeef")
    assert bad.status_code == 409
    assert bad.json()["status"] == "anchor_mismatch"

