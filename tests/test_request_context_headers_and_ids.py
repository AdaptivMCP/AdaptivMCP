from __future__ import annotations

import re

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.testclient import TestClient

import main
from github_mcp.mcp_server import context


async def _context_endpoint(_request):
    return JSONResponse(context.get_request_context())


async def _context_with_request_id_header(_request):
    # Simulate an upstream app that already sets X-Request-Id.
    return Response(
        "ok",
        headers={"x-request-id": "app-provided"},
        media_type="text/plain",
    )


def _build_app(routes):
    app = Starlette(routes=routes)
    return main._RequestContextMiddleware(app)


def test_request_context_honors_x_request_id_and_echoes_response_header():
    client = TestClient(_build_app([Route("/context", _context_endpoint)]))

    response = client.get(
        "/context?session_id=sess-1",
        headers={
            "x-request-id": "rid-123",
            "idempotency-key": "idem-abc",
        },
    )
    assert response.status_code == 200

    # Header is echoed back.
    assert response.headers["x-request-id"] == "rid-123"

    payload = response.json()
    assert payload["request_id"] == "rid-123"
    assert payload["session_id"] == "sess-1"
    assert payload["idempotency_key"] == "idem-abc"


def test_request_context_generates_request_id_when_missing():
    client = TestClient(_build_app([Route("/context", _context_endpoint)]))

    response = client.get("/context")
    assert response.status_code == 200

    rid = response.headers.get("x-request-id")
    assert rid
    assert re.fullmatch(r"[0-9a-f]{32}", rid), rid

    payload = response.json()
    assert payload["request_id"] == rid


def test_request_context_prefers_header_idempotency_over_query_string():
    client = TestClient(_build_app([Route("/context", _context_endpoint)]))

    response = client.get(
        "/context?idempotency_key=from-query",
        headers={"x-idempotency-key": "from-header"},
    )
    payload = response.json()
    assert payload["idempotency_key"] == "from-header"


def test_request_context_uses_query_idempotency_when_header_missing():
    client = TestClient(_build_app([Route("/context", _context_endpoint)]))

    response = client.get("/context?dedupe_key=from-query")
    payload = response.json()
    assert payload["idempotency_key"] == "from-query"


def test_request_context_does_not_overwrite_app_provided_x_request_id():
    client = TestClient(
        _build_app([Route("/context", _context_with_request_id_header)])
    )

    response = client.get("/context", headers={"x-request-id": "rid-ignored"})

    # Middleware should not clobber an explicit header already set by the app.
    assert response.headers["x-request-id"] == "app-provided"


def test_request_context_adds_server_anchor_header(monkeypatch):
    monkeypatch.setattr(main, "get_server_anchor", lambda: ("anchor-1", {"ok": True}))

    client = TestClient(_build_app([Route("/context", _context_endpoint)]))
    response = client.get("/context")

    assert response.headers["x-server-anchor"] == "anchor-1"


def test_request_context_skips_server_anchor_if_getter_raises(monkeypatch):
    def _boom():
        raise RuntimeError("no anchor")

    monkeypatch.setattr(main, "get_server_anchor", _boom)

    client = TestClient(_build_app([Route("/context", _context_endpoint)]))
    response = client.get("/context")

    assert "x-server-anchor" not in response.headers


@pytest.mark.asyncio
async def test_request_context_bypasses_non_http_scopes():
    called = {"count": 0}

    async def downstream(scope, receive, send):
        called["count"] += 1

    mw = main._RequestContextMiddleware(downstream)

    async def _receive():
        return {"type": "lifespan.startup"}

    async def _send(_message):
        return None

    await mw({"type": "lifespan"}, _receive, _send)
    assert called["count"] == 1
