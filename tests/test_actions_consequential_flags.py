import httpx
import importlib
import pytest

import main


def _expected_is_consequential(action: dict) -> bool:
    name = (action.get("name") or "").lower()
    tags = {str(t).lower() for t in action.get("meta", {}).get("tags", []) if t}

    if name in {"web_fetch", "web_search"} or "web" in tags:
        return True

    if name == "render_cli_command" or "render-cli" in tags:
        return True

    if name in {
        "workspace_create_branch",
        "workspace_delete_branch",
        "workspace_self_heal_branch",
    }:
        return True

    if "push" in name or any(t in {"push", "git-push", "git_push"} or "push" in t for t in tags):
        return True

    return False


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

        if main.server.WRITE_ALLOWED:
            assert bool(meta.get("auto_approved")) is True
        else:
            assert bool(meta.get("auto_approved")) is (not expected)
        assert bool(annotations.get("readOnlyHint")) is (not expected)


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
