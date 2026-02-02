from __future__ import annotations

from github_mcp.mcp_server import decorators as deco


def test_tool_short_desc_known_tools_are_present_and_bounded() -> None:
    for name in (
        "run_tests",
        "workspace_sync_to_remote",
        "describe_tool",
        "terminal_command",
    ):
        desc = deco._tool_short_desc(name)
        assert isinstance(desc, str)
        assert desc.strip(), name
        assert len(desc) <= 80, name


def test_tool_short_desc_unknown_tool_is_empty() -> None:
    assert deco._tool_short_desc("totally_unknown_tool_xyz") == ""


def test_tool_desc_bit_contains_separator_for_known_tools() -> None:
    bit = deco._tool_desc_bit("run_tests")
    assert "·" in bit
    assert "pytest" in bit.lower()
