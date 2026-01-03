import pytest


def _load_dependencies():
    """Load optional Starlette dependencies.

    We keep Starlette imports inside this helper so that the test module can be
    imported even when Starlette is not installed.
    """

    pytest.importorskip("starlette")

    from starlette.applications import Starlette
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    import main

    return Starlette, TrustedHostMiddleware, main


def _get_allowed_hosts(app, trusted_host_middleware_cls) -> list[str]:
    for middleware in app.user_middleware:
        if middleware.cls is trusted_host_middleware_cls:
            opts = getattr(middleware, "options", None)
            if opts is None:
                opts = getattr(middleware, "kwargs", {})
            return list((opts or {}).get("allowed_hosts", []))
    return []


def test_configure_trusted_hosts_includes_render_hostname(monkeypatch):
    Starlette, TrustedHostMiddleware, main = _load_dependencies()

    monkeypatch.setenv("ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "chatgpt-mcp.onrender.com")

    app = Starlette()
    main._configure_trusted_hosts(app)

    allowed_hosts = _get_allowed_hosts(app, TrustedHostMiddleware)
    assert "localhost" in allowed_hosts
    assert "chatgpt-mcp.onrender.com" in allowed_hosts


def test_configure_trusted_hosts_includes_render_url(monkeypatch):
    Starlette, TrustedHostMiddleware, main = _load_dependencies()

    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.test")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://render.example.test/sse")

    app = Starlette()
    main._configure_trusted_hosts(app)

    allowed_hosts = _get_allowed_hosts(app, TrustedHostMiddleware)
    assert "api.example.test" in allowed_hosts
    assert "render.example.test" in allowed_hosts
