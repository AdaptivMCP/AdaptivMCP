from github_mcp.mcp_server.schemas import _format_tool_args_preview, _sanitize_metadata_value


def test_sanitize_metadata_value_collapses_newlines_and_tabs():
    v = _sanitize_metadata_value({"a": "hello\nworld\t!\r\nagain"})
    assert v["a"] == "hello world ! again"


def test_tool_args_preview_is_single_line():
    preview = _format_tool_args_preview({"text": "line1\nline2\r\n", "note": "a\tb"})
    assert "\n" not in preview
    assert "\r" not in preview
