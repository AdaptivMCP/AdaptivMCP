import httpx
import pytest

import main


@pytest.mark.anyio
async def test_actions_endpoint_exposes_registered_tools():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as client:
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
