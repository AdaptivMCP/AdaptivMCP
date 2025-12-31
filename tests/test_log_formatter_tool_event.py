import logging

from github_mcp.config import _ColorFormatter


def test_formatter_renders_nested_tool_event_without_double_encoding():
    fmt = "%(levelname)s | %(name)s | %(message)s"
    formatter = _ColorFormatter(fmt, use_color=False)

    record = logging.LogRecord(
        name="github_mcp.tools",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="[tool event] tool_call.start | status=start | tool=list_tools",
        args=(),
        exc_info=None,
    )

    record.event = "tool_event"
    record.tool_event = {
        "event": "tool_call.start",
        "status": "start",
        "tool_name": "list_tools",
        "call_id": "abc",
        "request_keys": ["full_name", "ref"],
    }

    out = formatter.format(record)

    assert "data=" in out
    assert "\"tool_event\"" in out

    # If nested JSON was double-encoded, we'd see lots of backslash-escaped quotes.
    assert "\\\"" not in out


def test_formatter_does_not_emit_tool_json_field():
    fmt = "%(levelname)s | %(name)s | %(message)s"
    formatter = _ColorFormatter(fmt, use_color=False)

    record = logging.LogRecord(
        name="github_mcp.tools",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="[tool event] tool_call.ok | status=ok | tool=list_tools",
        args=(),
        exc_info=None,
    )

    record.event = "tool_event"
    record.tool_event = {"event": "tool_call.ok", "status": "ok", "tool_name": "list_tools"}

    out = formatter.format(record)
    assert "tool_json" not in out
