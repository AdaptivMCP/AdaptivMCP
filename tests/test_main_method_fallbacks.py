from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route

import main


class _NoRoutes:
    pass


def test_register_mcp_method_fallbacks_noop_without_app():
    main._register_mcp_method_fallbacks(None)
    main._register_mcp_method_fallbacks(_NoRoutes())


def test_register_mcp_method_fallbacks_adds_methods():
    async def messages_post(_request):
        return Response(status_code=204)

    async def sse_get(_request):
        return Response(status_code=204)

    app = Starlette(
        routes=[
            Route("/messages", messages_post, methods=["POST"]),
            Route("/sse", sse_get, methods=["GET"]),
        ]
    )

    main._register_mcp_method_fallbacks(app)

    methods_by_path: dict[str, set[str]] = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if path and methods:
            methods_by_path.setdefault(path, set()).update(methods)

    assert methods_by_path["/messages"] >= {"GET", "HEAD", "OPTIONS", "POST"}
    assert methods_by_path["/sse"] >= {"GET", "OPTIONS"}


def _count_routes(app, path: str, method: str) -> int:
    count = 0
    for route in app.routes:
        if getattr(route, "path", None) != path:
            continue
        methods = getattr(route, "methods", None) or set()
        if method in methods:
            count += 1
    return count


def test_register_mcp_method_fallbacks_is_idempotent():
    async def messages_post(_request):
        return Response(status_code=204)

    async def sse_get(_request):
        return Response(status_code=204)

    app = Starlette(
        routes=[
            Route("/messages", messages_post, methods=["POST"]),
            Route("/sse", sse_get, methods=["GET"]),
        ]
    )

    main._register_mcp_method_fallbacks(app)
    main._register_mcp_method_fallbacks(app)

    assert _count_routes(app, "/messages", "GET") == 1
    assert _count_routes(app, "/messages", "HEAD") == 1
    assert _count_routes(app, "/messages", "OPTIONS") == 1
    assert _count_routes(app, "/sse", "OPTIONS") == 1
