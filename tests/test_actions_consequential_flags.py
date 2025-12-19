import httpx
import importlib

import pytest

import main


def _expected_is_consequential(action: dict) -> bool:
    """Mirror the server's current /v1/actions serialization logic.

    The compat endpoint only marks a tool consequential if the tool metadata or
    annotations explicitly set it (it does not infer from names/tags).
    """

    meta = action.get("meta") or {}
    annotations = action.get("annotations") or {}

    is_consequential = meta.get("x-openai-isConsequential")
    if is_consequential is None:
        is_consequential = meta.get("openai/isConsequential")
    if is_consequential is None:
        is_consequential = annotations.get("isConsequential")

    return bool(is_consequential) if is_consequential is not None else False


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
async def test_actions_endpoint_marks_expected_consequential_tools():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=main.app), base_url="http://testserver"
    ) as client:
        response = await client.get("/v1/actions")

    assert response.status_code == 200
    data = response.json()
    actions = data.get("actions") or []
    assert actions, "expected at least one action in compatibility listing"

    expected_flags = {a["name"]: _expected_is_consequential(a) for a in actions}
    actual_flags = {a["name"]: _action_is_consequential_flag(a) for a in actions}

    assert actual_flags == expected_flags

    for action in actions:
        name = action["name"]
        expected = expected_flags[name]
        meta = action.get("meta") or {}
        annotations = action.get("annotations") or {}

        # When write actions are enabled, the server forces auto_approved for all tools.
        if main.server.WRITE_ALLOWED:
            assert bool(meta.get("auto_approved")) is True
        else:
            # When write actions are disabled, only non-consequential tools are auto-approved.
            assert bool(meta.get("auto_approved")) is (not expected)

        # readOnlyHint tracks whether the action mutates state (write_action flag).
        assert bool(annotations.get("readOnlyHint")) is (not meta.get("write_action"))


@pytest.mark.anyio
async def test_actions_endpoint_auto_approves_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        assert actions, "expected at least one action in compatibility listing"

        for action in actions:
            meta = action.get("meta") or {}
            assert bool(meta.get("auto_approved")) is True
    finally:
        monkeypatch.delenv("GITHUB_MCP_AUTO_APPROVE", raising=False)
        importlib.reload(main)
