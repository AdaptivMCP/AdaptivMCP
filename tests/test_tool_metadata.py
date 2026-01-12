from __future__ import annotations

import importlib.util

import pytest


if importlib.util.find_spec("jsonschema") is None:
    pytest.skip(
        "jsonschema is required for introspection metadata tests",
        allow_module_level=True,
    )

from github_mcp.main_tools import introspection


def test_tool_tags_returns_empty_list():
    class DummyTool:
        pass

    def dummy_fn():
        return "ok"

    assert introspection._tool_tags(DummyTool(), dummy_fn) == []
