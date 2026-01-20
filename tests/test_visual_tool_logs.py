import importlib
import os


def _reload_decorators_with_env(**env: str) -> object:
    """Reload github_mcp.mcp_server.decorators after setting env vars."""

    for k, v in env.items():
        os.environ[k] = v
    import github_mcp.mcp_server.decorators as decorators  # type: ignore

    return importlib.reload(decorators)


def test_preview_unified_diff_uses_hunk_line_numbers_when_color_disabled() -> None:
    decorators = _reload_decorators_with_env(
        ADAPTIV_MCP_LOG_COLOR="0",
        ADAPTIV_MCP_LOG_VISUALS="1",
        ADAPTIV_MCP_LOG_DIFF_SNIPPETS="1",
    )

    diff_text = """diff --git a/example.py b/example.py
index 0000000..1111111 100644
--- a/example.py
+++ b/example.py
@@ -10,2 +20,3 @@
 foo()
-bar()
+baz()
 qux()
"""

    rendered = decorators._preview_unified_diff(diff_text)

    # Old/new line numbers should reflect the hunk header, not 1..N.
    assert "   10    20 |" in rendered
    assert "   11       |" in rendered  # deletion advances old line only
    assert "       21 |" in rendered  # addition advances new line only


def test_preview_file_snippet_respects_start_line() -> None:
    decorators = _reload_decorators_with_env(
        ADAPTIV_MCP_LOG_COLOR="0",
        ADAPTIV_MCP_LOG_VISUALS="1",
        ADAPTIV_MCP_LOG_READ_SNIPPETS="1",
    )

    text = "a\nb\nc\n"
    rendered = decorators._preview_file_snippet("example.py", text, start_line=10)
    assert "  10│" in rendered
    assert "  11│" in rendered


def test_strip_internal_log_fields_preserves_log_keys_by_default() -> None:
    decorators = _reload_decorators_with_env(
        ADAPTIV_MCP_LOG_COLOR="0",
        ADAPTIV_MCP_LOG_VISUALS="1",
        ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS="0",
    )

    payload = {"ok": True, "__log_diff": "x", "__log_start_line": 12}
    cleaned = decorators._strip_internal_log_fields(payload)
    # Preserve the log keys so client-visible output matches the payload used
    # to render tool log visuals.
    assert cleaned == payload


def test_strip_internal_log_fields_can_restore_legacy_stripping() -> None:
    decorators = _reload_decorators_with_env(
        ADAPTIV_MCP_LOG_COLOR="0",
        ADAPTIV_MCP_LOG_VISUALS="1",
        ADAPTIV_MCP_STRIP_INTERNAL_LOG_FIELDS="1",
    )

    payload = {"ok": True, "__log_diff": "x", "__log_start_line": 12}
    cleaned = decorators._strip_internal_log_fields(payload)
    assert cleaned == {"ok": True}
