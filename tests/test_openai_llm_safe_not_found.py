from __future__ import annotations


from starlette.testclient import TestClient

import main


def test_openai_client_unknown_tool_detail_is_llm_safe() -> None:
    """OpenAI clients should not receive non-2xx responses for missing tools."""

    client = TestClient(main.app)
    resp = client.get(
        "/tools/definitely_not_a_real_tool",
        headers={"x-openai-assistant-id": "test"},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Tool-Original-Status") == "404"
    payload = resp.json()
    assert "Unknown tool" in (payload.get("error") or "")


def test_openai_client_unknown_invocation_status_is_llm_safe() -> None:
    client = TestClient(main.app)
    resp = client.get(
        "/tool_invocations/not-a-real-invocation-id",
        headers={"x-openai-assistant-id": "test"},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Tool-Original-Status") == "404"
    payload = resp.json()
    assert payload.get("error") == "Unknown invocation id"


def test_openai_client_unknown_invocation_cancel_is_llm_safe() -> None:
    client = TestClient(main.app)
    resp = client.post(
        "/tool_invocations/not-a-real-invocation-id/cancel",
        headers={"x-openai-assistant-id": "test"},
    )

    assert resp.status_code == 200
    assert resp.headers.get("X-Tool-Original-Status") == "404"
    payload = resp.json()
    assert payload.get("error") == "Unknown invocation id"

