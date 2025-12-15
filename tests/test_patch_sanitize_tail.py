import pytest

from github_mcp.workspace import _sanitize_patch_tail


RAW_DIFF = """diff --git a/foo.txt b/foo.txt
index 0000000..1111111 100644
--- a/foo.txt
+++ b/foo.txt
@@ -0,0 +1 @@
+hello
"""


@pytest.mark.parametrize("junk", ["```", "```diff", "```patch", "}", "}}"])
def test_sanitize_patch_tail_strips_trailing_junk_lines_for_diffs(junk):
    patch = RAW_DIFF + junk + "\n"
    out = _sanitize_patch_tail(patch)
    assert out.startswith("diff --git")
    assert out.rstrip("\n").endswith("+hello")
    assert junk not in out


def test_sanitize_patch_tail_preserves_final_newline_when_present():
    patch = RAW_DIFF + "```\n"
    out = _sanitize_patch_tail(patch)
    assert out.endswith("\n")


def test_sanitize_patch_tail_does_not_modify_non_diff_input():
    s = "not a diff\n```\n}}\n"
    assert _sanitize_patch_tail(s) == s
