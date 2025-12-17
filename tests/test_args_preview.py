from __future__ import annotations

from github_mcp.mcp_server.schemas import _format_tool_args_preview


def test_args_preview_summarizes_large_text_fields() -> None:
    preview = _format_tool_args_preview(
        {
            "path": "README.md",
            "updated_content": "line1\nline2\nline3\n",
            "command": "python -c \"print('hello')\"",
        }
    )

    # Large string fields should be summarized, not inlined.
    assert "updated_content" in preview
    assert "<str len=" in preview
    assert "line1" not in preview

    # Ensure the preview is single-line.
    assert "\n" not in preview
