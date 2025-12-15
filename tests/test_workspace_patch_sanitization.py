from github_mcp.workspace import _sanitize_patch_head


def test_sanitize_patch_head_strips_leading_fence() -> None:
    patch = """```diff

diff --git a/foo.txt b/foo.txt
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/foo.txt
@@ -0,0 +1 @@
+hello
```
"""

    out = _sanitize_patch_head(patch)
    assert out.lstrip().startswith("diff --git")
    assert not out.lstrip().startswith("```")


def test_sanitize_patch_head_strips_leading_blank_lines() -> None:
    patch = """\n\n\n--- a/a.txt
+++ b/a.txt
@@ -1 +1 @@
-a
+b
"""
    out = _sanitize_patch_head(patch)
    assert out.startswith("--- a/a.txt")


def test_sanitize_patch_head_drops_prefix_before_diff() -> None:
    patch = """{\"foo\": \"bar\"}
not a diff line

diff --git a/a.txt b/a.txt
index e69de29..4b825dc 100644
--- a/a.txt
+++ b/a.txt
@@ -0,0 +1 @@
+x
"""
    out = _sanitize_patch_head(patch)
    assert out.startswith("diff --git a/a.txt b/a.txt")


def test_sanitize_patch_head_noop_for_non_diffs() -> None:
    s = "hello world\n```\n"
    assert _sanitize_patch_head(s) == s


def test_sanitize_patch_head_preserves_newline_behavior() -> None:
    patch_no_nl = "diff --git a/a b/a\n--- a/a\n+++ b/a"
    out = _sanitize_patch_head(patch_no_nl)
    assert not out.endswith("\n")

    patch_with_nl = patch_no_nl + "\n"
    out2 = _sanitize_patch_head(patch_with_nl)
    assert out2.endswith("\n")
