from __future__ import annotations

from github_mcp.main_tools import introspection


def test_tool_tags_returns_empty_list():
    class DummyTool:
        pass

    def dummy_fn():
        return "ok"

    assert introspection._tool_tags(DummyTool(), dummy_fn) == []
