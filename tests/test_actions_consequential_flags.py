import importlib

import os

os.environ.setdefault("GITHUB_MCP_COMPACT_METADATA", "0")

import importlib
import httpx
import pytest

import main


def _action_is_consequential_flag(action: dict) -> bool:
    meta = action.get("meta") or {}
    annotations = action.get("annotations") or {}

    candidates = [
        action.get("x-openai-isConsequential"),
        action.get("isConsequential"),
        meta.get("x-openai-isConsequential"),
        meta.get("openai/isConsequential"),
        annotations.get("isConsequential"),
    ]

    for candidate in candidates:
        if candidate is not None:
            return bool(candidate)
    return False


@pytest.mark.anyio
async def test_actions_mark_web_and_push_as_consequential_when_auto_approve_on(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GITHUB_MCP_AUTO_APPROVE", "true")
    updated_main = importlib.reload(main)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=updated_main.app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/v1/actions")

        assert response.status_code == 200
        actions = response.json().get("actions") or []
        flags = {a["name"]: _action_is_consequential_flag(a) for a in actions}

        assert flags.get("web_fetch") is True
        assert flags.get("terminal_push") is True
        assert flags.get("create_pull_request") is False
    finally:
        monkeypatch.delenv("GITHUB_MCP_AUTO_APPROVE", raising=False)
        importlib.reload(main)


@pytest.mark.anyio
async def test_actions_mark_writes_when_auto_approve_off():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v1/actions")

    assert response.status_code == 200
    actions = response.json().get("actions") or []
    flags = {a["name"]: _action_is_consequential_flag(a) for a in actions}

    assert flags.get("web_fetch") is True
    assert flags.get("terminal_push") is True
    # PR flow should remain ungated
    assert flags.get("create_pull_request") is False
