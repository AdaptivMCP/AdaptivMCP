import httpx
import pytest

import main


@pytest.mark.anyio
async def test_actions_endpoint_exposes_registered_tools():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v1/actions")

    assert response.status_code == 200
    data = response.json()
    assert "actions" in data
    assert isinstance(data["actions"], list)
    assert data["actions"], "expected at least one action in compatibility listing"

    sample = data["actions"][0]
    assert sample["name"]
    assert "parameters" in sample
    assert isinstance(sample["parameters"], dict)

    # Prefer a human-friendly title when the server provides one.
    apply_action = next(
        (a for a in data["actions"] if a.get("name") == "apply_text_update_and_commit"), None
    )
    assert apply_action is not None
    assert apply_action.get("title"), "expected actions endpoint to expose a title/display label"
    assert apply_action["title"] != apply_action["name"], (
        "expected title to differ from raw tool name"
    )

    meta = apply_action.get("meta") or {}
    assert "openai/toolInvocation/invoking" in meta
    assert "openai/toolInvocation/invoked" in meta
    assert "openai/visibility" in meta
