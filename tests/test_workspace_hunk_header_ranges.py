from github_mcp import workspace as ws


def test_is_hunk_header_with_ranges_accepts_standard_headers():
    assert ws._is_hunk_header_with_ranges("@@ -1 +1 @@") is True
    assert ws._is_hunk_header_with_ranges("@@ -1,3 +2,4 @@") is True


def test_is_hunk_header_with_ranges_accepts_trailing_context():
    # Unified diff headers may include a trailing function/context after the closing @@.
    assert ws._is_hunk_header_with_ranges("@@ -1,3 +2,4 @@ some_function") is True
    assert ws._is_hunk_header_with_ranges("@@ -10 +20 @@ class Foo") is True


def test_looks_like_rangeless_git_patch_ignores_headers_with_context():
    patch = (
        "diff --git a/note.txt b/note.txt\n"
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@ -1 +1 @@ some_context\n"
        "-old\n"
        "+new\n"
    )
    assert ws._looks_like_rangeless_git_patch(patch) is False


def test_looks_like_rangeless_git_patch_detects_bare_hunks():
    patch = (
        "diff --git a/note.txt b/note.txt\n"
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@\n"
        "-old\n"
        "+new\n"
    )
    assert ws._looks_like_rangeless_git_patch(patch) is True


def test_patch_has_hunk_header_with_ranges_accepts_trailing_context():
    patch = (
        "diff --git a/note.txt b/note.txt\n"
        "--- a/note.txt\n"
        "+++ b/note.txt\n"
        "@@ -1 +1 @@ trailing\n"
        "-old\n"
        "+new\n"
    )
    assert ws._patch_has_hunk_header_with_ranges(patch) is True
