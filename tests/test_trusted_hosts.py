import pytest


def _load_dependencies():
    """Load optional Starlette dependencies.

    We keep Starlette imports inside this helper so that the test module can be
    imported even when Starlette is not installed.
    """

    pytest.importorskip("starlette")

    from starlette.applications import Starlette

    import main

    return Starlette, main


def test_configure_trusted_hosts_is_noop(monkeypatch):
    Starlette, main = _load_dependencies()

    monkeypatch.setenv("ALLOWED_HOSTS", "localhost")
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "chatgpt-mcp.onrender.com")

    app = Starlette()
    app.user_middleware.append(object())
    main._configure_trusted_hosts(app)

    assert len(app.user_middleware) == 1
