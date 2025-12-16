import main


def test_http_app_exposes_sse_transport():
    routes = [route for route in main.app.routes if hasattr(route, "path")]

    paths = {route.path for route in routes}
    assert "/sse" in paths, "expected SSE endpoint to be exposed for ChatGPT controllers"
    assert "/messages" in paths, "expected message endpoint to be exposed for SSE transport"

    sse_route = next(route for route in routes if route.path == "/sse")
    assert "GET" in sse_route.methods
