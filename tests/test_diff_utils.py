from __future__ import annotations

import re

from github_mcp import diff_utils


def test_sha1_8_is_stable_and_short() -> None:
    a1 = diff_utils.sha1_8("hello")
    a2 = diff_utils.sha1_8("hello")
    b = diff_utils.sha1_8("world")

    assert a1 == a2
    assert a1 != b
    assert len(a1) == 8
    assert re.fullmatch(r"[0-9a-f]{8}", a1) is not None


def test_build_unified_diff_contains_headers_and_hunk() -> None:
    before = "a\nold\n"
    after = "a\nnew\n"

    out = diff_utils.build_unified_diff(before, after, fromfile="x", tofile="y", n=1)

    assert out.startswith("--- x\n+++ y\n@@")
    assert "-old" in out
    assert "+new" in out


def test_diff_stats_counts_only_content_lines() -> None:
    diff_text = "\n".join(
        [
            "--- a",
            "+++ b",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            " unchanged",
        ]
    )

    stats = diff_utils.diff_stats(diff_text)
    assert stats.added == 1
    assert stats.removed == 1


def test_colorize_unified_diff_wraps_expected_lines() -> None:
    diff_text = "\n".join(
        [
            "--- a",
            "+++ b",
            "@@ -1 +1 @@",
            "-old",
            "+new",
            " unchanged",
        ]
    )
    colored = diff_utils.colorize_unified_diff(diff_text)

    assert f"{diff_utils.ANSI_DIM}--- a{diff_utils.ANSI_RESET}" in colored
    assert f"{diff_utils.ANSI_DIM}+++ b{diff_utils.ANSI_RESET}" in colored
    assert f"{diff_utils.ANSI_CYAN}@@ -1 +1 @@{diff_utils.ANSI_RESET}" in colored
    assert f"{diff_utils.ANSI_RED}-old{diff_utils.ANSI_RESET}" in colored
    assert f"{diff_utils.ANSI_GREEN}+new{diff_utils.ANSI_RESET}" in colored
    assert " unchanged" in colored


def test_colorize_unified_diff_is_noop_for_empty() -> None:
    assert diff_utils.colorize_unified_diff("") == ""
