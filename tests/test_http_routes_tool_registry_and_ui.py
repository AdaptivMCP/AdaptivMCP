from __future__ import annotations

from starlette.testclient import TestClient

import main


def test_ui_json_includes_core_endpoints():
    client = TestClient(main.app)

    resp = client.get("/ui.json")
    assert resp.status_code == 200
    payload = resp.json()

    endpoints = payload.get("endpoints") or {}
    assert endpoints.get("health", "").endswith("/healthz")
    assert endpoints.get("tools", "").endswith("/tools")
    assert endpoints.get("resources", "").endswith("/resources")

    # ChatGPT/OpenAI connectors increasingly use Streamable HTTP at /mcp.
    assert endpoints.get("mcp", "").endswith("/mcp")

    # Backwards compatibility: keep the SSE transport advertised.
    assert endpoints.get("sse", "").endswith("/sse")
    assert endpoints.get("messages", "").endswith("/messages")


def test_mcp_endpoint_is_mounted():
    client = TestClient(main.app)

    # We don't assert a specific transport behavior here (it may vary by MCP SDK
    # version). We only require that /mcp is not missing.
    resp = client.get("/mcp")
    assert resp.status_code != 404

    preflight = client.options("/mcp")
    assert preflight.status_code != 404
