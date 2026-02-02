from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import main
from github_mcp.mcp_server import context


@pytest.mark.asyncio
async def test_cache_control_middleware_dedupes_starts_and_ignores_post_completion():
    sent: list[dict] = []

    async def app(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        # Duplicate start should be ignored.
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"x-duplicate", b"1")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})
        # Anything after the response completes should be ignored.
        await send({"type": "http.response.start", "status": 500, "headers": []})
        await send({"type": "http.response.body", "body": b"late", "more_body": False})

    middleware = main._CacheControlMiddleware(app)

    scope = {"type": "http", "path": "/api"}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)

    assert [m.get("type") for m in sent] == [
        "http.response.start",
        "http.response.body",
    ]
    headers = dict(sent[0].get("headers") or [])
    assert headers[b"cache-control"] == b"no-store"


@pytest.mark.asyncio
async def test_cache_control_middleware_handles_malformed_header_keys():
    sent: list[dict] = []

    async def app(_scope, _receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(None, b"oops")],
            }
        )
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    middleware = main._CacheControlMiddleware(app)

    scope = {"type": "http", "path": "/api"}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)

    assert sent and sent[0]["type"] == "http.response.start"
    headers = dict(sent[0].get("headers") or [])
    assert headers[b"cache-control"] == b"no-store"


@pytest.mark.asyncio
async def test_middlewares_passthrough_non_http_scopes():
    seen: dict[str, object] = {}

    async def app(scope, _receive, send):
        seen["scope"] = scope
        await send({"type": "websocket.close", "code": 1000})

    cache_mw = main._CacheControlMiddleware(app)
    reqctx_mw = main._RequestContextMiddleware(app)

    scope = {"type": "websocket"}

    async def receive():
        return {"type": "websocket.disconnect"}

    async def send(_message):
        pass

    await cache_mw(scope, receive, send)
    await reqctx_mw(scope, receive, send)

    assert seen["scope"]["type"] == "websocket"


async def _context_endpoint(_request):
    return JSONResponse(context.get_request_context())


def _build_request_context_app(monkeypatch):
    # Make x-server-anchor deterministic for assertions.
    monkeypatch.setattr(main, "get_server_anchor", lambda: ("anchor-123", {}))
    app = Starlette(routes=[Route("/context", _context_endpoint)])
    return main._RequestContextMiddleware(app)


def test_request_context_parses_session_and_idempotency_from_querystring(monkeypatch):
    client = TestClient(_build_request_context_app(monkeypatch))

    response = client.get("/context?session_id=sess-1&idempotency_key=idem-1")
    payload = response.json()

    assert payload["session_id"] == "sess-1"
    assert payload["idempotency_key"] == "idem-1"
    assert response.headers["x-server-anchor"] == "anchor-123"
    assert "x-request-id" in response.headers


def test_request_context_header_idempotency_wins_over_query(monkeypatch):
    client = TestClient(_build_request_context_app(monkeypatch))

    response = client.get(
        "/context?session_id=sess-1&idempotency_key=query-wont-win",
        headers={"idempotency-key": "hdr-wins"},
    )
    payload = response.json()

    assert payload["idempotency_key"] == "hdr-wins"


def test_request_context_honors_existing_response_request_id_header(monkeypatch):
    monkeypatch.setattr(main, "get_server_anchor", lambda: ("anchor-123", {}))

    async def endpoint(_request):
        return JSONResponse(
            {"ctx": context.get_request_context()},
            headers={"x-request-id": "already-set"},
        )

    app = main._RequestContextMiddleware(Starlette(routes=[Route("/ctx", endpoint)]))
    client = TestClient(app)

    response = client.get("/ctx", headers={"x-request-id": "req-xyz"})
    payload = response.json()["ctx"]

    # Middleware should not clobber response's x-request-id.
    assert response.headers["x-request-id"] == "already-set"
    # But request-scoped context should still reflect the incoming request id.
    assert payload["request_id"] == "req-xyz"
    assert response.headers["x-server-anchor"] == "anchor-123"
