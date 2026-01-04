import sys
import types

import pytest


def _install_starlette_stubs() -> None:
    """Install minimal Starlette stubs for import-time evaluation.

    These tests validate payload normalization and tool-registry glue code.
    The project supports running without Starlette installed, so we provide
    a minimal stub implementation. The stub set must be complete enough to
    avoid breaking other tests that may import Starlette middleware helpers.
    """

    starlette_module = types.ModuleType("starlette")

    # starlette.applications
    applications_module = types.ModuleType("starlette.applications")

    class Starlette:  # pragma: no cover - stub
        def __init__(self, *args, **kwargs):
            self.user_middleware = []

        def add_middleware(self, cls, **options):
            # Mirror the interface used by main._configure_trusted_hosts
            self.user_middleware.append(types.SimpleNamespace(cls=cls, options=options))

    applications_module.Starlette = Starlette

    # starlette.middleware.trustedhost
    middleware_module = types.ModuleType("starlette.middleware")
    trustedhost_module = types.ModuleType("starlette.middleware.trustedhost")

    class TrustedHostMiddleware:  # pragma: no cover - stub
        pass

    trustedhost_module.TrustedHostMiddleware = TrustedHostMiddleware

    # starlette.requests / responses
    requests_module = types.ModuleType("starlette.requests")
    responses_module = types.ModuleType("starlette.responses")

    staticfiles_module = types.ModuleType("starlette.staticfiles")

    class StaticFiles:  # pragma: no cover - stub
        def __init__(self, *args, **kwargs):
            pass

    staticfiles_module.StaticFiles = StaticFiles

    class Request:  # pragma: no cover - stub
        pass

    class Response:  # pragma: no cover - stub
        pass

    class JSONResponse(Response):  # pragma: no cover - stub
        pass

    class PlainTextResponse(Response):  # pragma: no cover - stub
        pass

    requests_module.Request = Request
    responses_module.Response = Response
    responses_module.JSONResponse = JSONResponse
    responses_module.PlainTextResponse = PlainTextResponse

    # Register modules.
    sys.modules.setdefault("starlette", starlette_module)
    sys.modules.setdefault("starlette.applications", applications_module)
    sys.modules.setdefault("starlette.middleware", middleware_module)
    sys.modules.setdefault("starlette.middleware.trustedhost", trustedhost_module)
    sys.modules.setdefault("starlette.requests", requests_module)
    sys.modules.setdefault("starlette.responses", responses_module)
    sys.modules.setdefault("starlette.staticfiles", staticfiles_module)


@pytest.fixture
def tool_registry_module(monkeypatch):
    _install_starlette_stubs()
    import importlib

    return importlib.import_module("github_mcp.http_routes.tool_registry")


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"owner": "octo", "repo": "example"}, {"owner": "octo", "repo": "example"}),
        (
            {
                "args": [
                    {"name": "owner", "value": "octo"},
                    {"name": "repo", "value": "example"},
                ]
            },
            {"owner": "octo", "repo": "example"},
        ),
        (
            {"args": [{"owner": "octo"}, {"repo": "example"}]},
            {"owner": "octo", "repo": "example"},
        ),
        (
            [("owner", "octo"), ("repo", "example")],
            {"owner": "octo", "repo": "example"},
        ),
        (None, {}),
    ],
)
def test_normalize_payload(tool_registry_module, payload, expected):
    assert tool_registry_module._normalize_payload(payload) == expected
