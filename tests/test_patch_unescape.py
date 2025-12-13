import pytest

from github_mcp.workspace import _maybe_unescape_unified_diff
from github_mcp.tools_workspace import _coerce_unified_diff_text


RAW_DIFF = """diff --git a/foo.txt b/foo.txt
index 0000000..1111111 100644
--- a/foo.txt
+++ b/foo.txt
@@ -0,0 +1 @@
+hello
"""


@pytest.mark.parametrize("fn", [_maybe_unescape_unified_diff, _coerce_unified_diff_text])
def test_unescapes_single_line_diff_with_literal_backslash_n(fn):
    escaped = RAW_DIFF.replace("\n", "\\n")
    assert "\n" not in escaped
    assert "\\n" in escaped

    out = fn(escaped)
    assert "\n" in out
    assert out.startswith("diff --git")
    assert "+hello" in out


@pytest.mark.parametrize("fn", [_maybe_unescape_unified_diff, _coerce_unified_diff_text])
def test_does_not_touch_normal_multiline_diff(fn):
    out = fn(RAW_DIFF)
    assert out == RAW_DIFF


@pytest.mark.parametrize("fn", [_maybe_unescape_unified_diff, _coerce_unified_diff_text])
def test_does_not_unescape_non_diff_strings(fn):
    s = "not a diff but has \\n literally"
    out = fn(s)
    assert out == s
