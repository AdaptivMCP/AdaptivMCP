from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient

import main


def _build_cache_control_app():
    async def static_asset(_request):
        return Response("ok", media_type="application/javascript")

    async def static_html(_request):
        return Response(
            "ok",
            media_type="text/html",
            headers={"Cache-Control": "public, max-age=0"},
        )

    async def static_explicit(_request):
        return Response(
            "ok",
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=60"},
        )

    async def api_endpoint(_request):
        return Response("ok", headers={"Cache-Control": "public"})

    app = Starlette(
        routes=[
            Route("/static/app.js", static_asset),
            Route("/static/index.html", static_html),
            Route("/static/explicit.css", static_explicit),
            Route("/api", api_endpoint),
        ]
    )
    return main._CacheControlMiddleware(app)


def test_cache_control_middleware_sets_expected_headers():
    client = TestClient(_build_cache_control_app())

    response = client.get("/static/app.js")
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"

    response = client.get("/static/index.html")
    assert response.headers["cache-control"] == "no-store"

    response = client.get("/static/explicit.css")
    assert response.headers["cache-control"] == "public, max-age=60"

    response = client.get("/api")
    assert response.headers["cache-control"] == "no-store"


def test_register_mcp_fallback_route_adds_methods():
    app = Starlette()

    main._register_mcp_fallback_route(app)

    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            methods_by_path.setdefault(path, set()).update(methods)

    assert methods_by_path["/mcp"] >= {"GET", "HEAD", "POST", "OPTIONS"}
    assert methods_by_path["/mcp/"] >= {"GET", "HEAD", "POST", "OPTIONS"}
