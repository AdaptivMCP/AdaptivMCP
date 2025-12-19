import importlib

import pytest

from github_mcp.http_routes.actions_compat import serialize_actions_for_compatibility


def test_compact_metadata_includes_consequential_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_MCP_COMPACT_METADATA", "1")

    import main as main_module

    reloaded = importlib.reload(main_module)

    try:
        actions = serialize_actions_for_compatibility(reloaded)

        target = next(action for action in actions if action.get("name") == "get_server_config")

        meta = target.get("meta") or {}
        annotations = target.get("annotations") or {}

        assert meta.get("write_action") is False
        assert meta.get("openai/isConsequential") is False
        assert meta.get("x-openai-isConsequential") is False
        assert annotations.get("readOnlyHint") is True
    finally:
        monkeypatch.delenv("GITHUB_MCP_COMPACT_METADATA", raising=False)
        importlib.reload(main_module)
