import sys
import types

import pytest


def _install_starlette_stubs() -> None:
    starlette_module = types.ModuleType("starlette")
    requests_module = types.ModuleType("starlette.requests")
    responses_module = types.ModuleType("starlette.responses")

    class Request:  # pragma: no cover - stub for import
        pass

    class Response:  # pragma: no cover - stub for import
        pass

    class JSONResponse(Response):  # pragma: no cover - stub for import
        pass

    requests_module.Request = Request
    responses_module.Response = Response
    responses_module.JSONResponse = JSONResponse

    sys.modules.setdefault("starlette", starlette_module)
    sys.modules.setdefault("starlette.requests", requests_module)
    sys.modules.setdefault("starlette.responses", responses_module)


_install_starlette_stubs()

from github_mcp.http_routes import tool_registry


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"owner": "octo", "repo": "example"}, {"owner": "octo", "repo": "example"}),
        (
            {"args": [{"name": "owner", "value": "octo"}, {"name": "repo", "value": "example"}]},
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
def test_normalize_payload(payload, expected):
    assert tool_registry._normalize_payload(payload) == expected
