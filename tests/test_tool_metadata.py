from __future__ import annotations

import importlib.util

import pytest


if importlib.util.find_spec("jsonschema") is None:
    pytest.skip("jsonschema is required for introspection metadata tests", allow_module_level=True)

from github_mcp.main_tools import introspection


def test_tool_tags_falls_back_to_wrapper_tags():
    class DummyTool:
        pass

    def dummy_fn():
        return "ok"

    dummy_fn.__mcp_tags__ = ["alpha", "beta"]
    assert introspection._tool_tags(DummyTool(), dummy_fn) == ["alpha", "beta"]
