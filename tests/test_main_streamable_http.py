from __future__ import annotations

from starlette.testclient import TestClient

import main


def test_streamable_http_probe_uses_supported_factory() -> None:
    client = TestClient(main.app)

    response = client.get("/mcp")
    payload = response.json()

    supports_streamable = any(
        callable(getattr(main.server.mcp, attr, None))
        for attr in ("http_app", "streamable_http_app")
    )

    if supports_streamable:
        assert response.status_code == 200
        assert payload.get("ok") is True
        assert payload.get("endpoint") == "/mcp"
    else:
        assert response.status_code == 200
        assert payload.get("ok") is False
