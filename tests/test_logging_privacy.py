import logging

import pytest

import github_mcp.mcp_server.context as ctx
from github_mcp.mcp_server import decorators


@pytest.fixture(autouse=True)
def _restore_registry_and_events():
    original_registry = list(decorators._REGISTERED_MCP_TOOLS)
    original_events = list(getattr(ctx, "RECENT_TOOL_EVENTS", []))
    original_total = getattr(ctx, "RECENT_TOOL_EVENTS_TOTAL", 0)
    original_dropped = getattr(ctx, "RECENT_TOOL_EVENTS_DROPPED", 0)
    try:
        if hasattr(ctx.RECENT_TOOL_EVENTS, "clear"):
            ctx.RECENT_TOOL_EVENTS.clear()
        else:
            ctx.RECENT_TOOL_EVENTS[:] = []
        ctx.RECENT_TOOL_EVENTS_TOTAL = 0
        ctx.RECENT_TOOL_EVENTS_DROPPED = 0
        decorators._REGISTERED_MCP_TOOLS[:] = []
        yield
    finally:
        decorators._REGISTERED_MCP_TOOLS[:] = original_registry
        if hasattr(ctx.RECENT_TOOL_EVENTS, "clear"):
            ctx.RECENT_TOOL_EVENTS.clear()
            ctx.RECENT_TOOL_EVENTS.extend(original_events)
        else:
            ctx.RECENT_TOOL_EVENTS[:] = original_events
        ctx.RECENT_TOOL_EVENTS_TOTAL = original_total
        ctx.RECENT_TOOL_EVENTS_DROPPED = original_dropped


def test_tool_logs_do_not_include_location(caplog: pytest.LogCaptureFixture):
    @decorators.mcp_tool(name="privacy_tool", write_action=False, description="demo")
    def _privacy_tool(full_name: str, ref: str, path: str) -> str:
        return "ok"

    caplog.set_level(logging.DETAILED, logger="github_mcp.tools")
    _privacy_tool(full_name="owner/repo", ref="main", path="some/file")

    messages = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in ("owner/repo", "main", "some/file"):
        assert forbidden not in messages

    for record in caplog.records:
        assert not hasattr(record, "repo")
        assert not hasattr(record, "ref")
        assert not hasattr(record, "path")


def test_recent_tool_events_omit_location_data():
    @decorators.mcp_tool(name="event_tool", write_action=False, description="demo")
    def _event_tool(full_name: str, ref: str, path: str) -> str:
        return "ok"

    _event_tool(full_name="owner/repo", ref="main", path="some/file")

    events = list(ctx.RECENT_TOOL_EVENTS)
    assert events
    last_event = events[-1]
    for key in ("repo", "ref", "path"):
        assert key not in last_event

    assert "owner/repo" not in last_event.get("user_message", "")


def test_default_tags_are_not_injected():
    @decorators.mcp_tool(name="tag_tool", write_action=False, description="demo")
    def _tag_tool() -> None:
        return None

    tool_obj = decorators._REGISTERED_MCP_TOOLS[-1][0]
    tags = getattr(tool_obj, "tags", [])
    assert "read" not in set(tags)
    assert "write" not in set(tags)
