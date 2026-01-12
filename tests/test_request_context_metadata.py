from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import main
from github_mcp.mcp_server import context


async def _context_endpoint(request):
    return JSONResponse(context.get_request_context())


def _build_app():
    app = Starlette(routes=[Route("/context", _context_endpoint)])
    return main._RequestContextMiddleware(app)


def test_request_context_includes_chatgpt_metadata():
    client = TestClient(_build_app())
    response = client.get(
        "/context",
        headers={
            "x-openai-conversation-id": "conv-123",
            "x-openai-assistant-id": "asst-456",
            "x-openai-project-id": "proj-789",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["chatgpt"] == {
        "conversation_id": "conv-123",
        "assistant_id": "asst-456",
        "project_id": "proj-789",
    }
