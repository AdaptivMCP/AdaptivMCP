import importlib

import pytest


def _reload_main(monkeypatch: pytest.MonkeyPatch, value: str | None):
    if value is None:
        monkeypatch.delenv("GITHUB_MCP_AUTO_APPROVE", raising=False)
    else:
        monkeypatch.setenv("GITHUB_MCP_AUTO_APPROVE", value)

    import main as main_module

    return importlib.reload(main_module)


def test_write_allowed_defaults_false(monkeypatch: pytest.MonkeyPatch):
    module = _reload_main(monkeypatch, None)
    assert module.WRITE_ALLOWED is False
    assert module.AUTO_APPROVE_ENABLED is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", "y"])
def test_write_allowed_accepts_truthy_strings(monkeypatch: pytest.MonkeyPatch, value: str):
    module = _reload_main(monkeypatch, value)
    assert module.WRITE_ALLOWED is True


def test_authorize_write_actions_toggles_from_manual(monkeypatch: pytest.MonkeyPatch):
    module = _reload_main(monkeypatch, None)
    assert module.WRITE_ALLOWED is False

    result = module.authorize_write_actions(approved=True)
    assert result["write_allowed"] is True
    assert module.WRITE_ALLOWED is True


def test_authorize_write_actions_toggles_from_auto(monkeypatch: pytest.MonkeyPatch):
    module = _reload_main(monkeypatch, "true")
    assert module.WRITE_ALLOWED is True

    result = module.authorize_write_actions(approved=False)
    assert result["write_allowed"] is False
    assert module.WRITE_ALLOWED is False


def test_write_gate_blocks_push_when_auto_approve_enabled(monkeypatch: pytest.MonkeyPatch):
    module = _reload_main(monkeypatch, "true")

    module._ensure_write_allowed("push attempt", target_ref="main", intent="push")


def test_write_gate_allows_non_push_when_auto_approve_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    module = _reload_main(monkeypatch, "true")

    module._ensure_write_allowed("update file", target_ref="feature/foo")


def test_write_gate_allows_writes_when_auto_approve_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    module = _reload_main(monkeypatch, None)

    module._ensure_write_allowed("update file", target_ref="feature/foo")


def test_write_gate_allows_pr_and_non_harmful(monkeypatch: pytest.MonkeyPatch):
    module = _reload_main(monkeypatch, None)

    module._ensure_write_allowed(
        "comment on issue", target_ref=None, intent="non_harm"
    )
    module._ensure_write_allowed("create pr", target_ref="main", intent="pr")


@pytest.mark.asyncio
async def test_get_server_config_manual_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _reload_main(monkeypatch, None)

    config = await module.get_server_config()
    assert config["write_allowed"] is False

    write_policy = config["approval_policy"]["write_actions"]
    assert write_policy["auto_approved"] is False
    assert write_policy["requires_authorization"] is True
    assert write_policy["toggle_tool"] == "authorize_write_actions"


@pytest.mark.asyncio
async def test_get_server_config_auto_approve_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _reload_main(monkeypatch, "true")

    config = await module.get_server_config()
    assert config["write_allowed"] is True

    write_policy = config["approval_policy"]["write_actions"]
    assert write_policy["auto_approved"] is True
    assert write_policy["requires_authorization"] is False
    assert write_policy["toggle_tool"] == "authorize_write_actions"
