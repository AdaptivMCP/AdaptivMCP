from __future__ import annotations

from github_mcp.diff_utils import (
    ANSI_CYAN,
    ANSI_GREEN,
    ANSI_RED,
    ANSI_RESET,
    build_unified_diff,
    colorize_unified_diff,
    diff_stats,
    truncate_diff,
)


def test_unified_diff_stats_and_colors() -> None:
    before = "a\nold\n"
    after = "a\nnew\n"

    diff = build_unified_diff(before, after, fromfile="a/x.txt", tofile="b/x.txt")
    stats = diff_stats(diff)
    assert stats.added == 1
    assert stats.removed == 1

    colored = colorize_unified_diff(diff)

    # Hunk header is colored.
    assert ANSI_CYAN in colored

    # The content lines are colored.
    assert f"{ANSI_RED}-old{ANSI_RESET}" in colored
    assert f"{ANSI_GREEN}+new{ANSI_RESET}" in colored


def test_truncate_diff_by_lines_and_chars() -> None:
    diff = "\n".join([f"+line{i}" for i in range(500)])

    truncated = truncate_diff(diff, max_lines=10, max_chars=10_000)
    assert "… (+" in truncated

    truncated2 = truncate_diff(diff, max_lines=500, max_chars=20)
    assert "… (+" in truncated2
