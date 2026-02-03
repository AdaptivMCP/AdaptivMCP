from __future__ import annotations

import github_mcp.mcp_server.decorators as dec


def test_clip_text_preserves_tail_chars() -> None:
    text = ("A" * 100) + "TAILXYZ"
    clipped = dec._clip_text(
        text,
        max_lines=1,
        max_chars=60,
        enabled=False,
    )

    assert "TAILXYZ" in clipped


def test_clip_text_limits_marker_length() -> None:
    text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    clipped = dec._clip_text(
        text,
        max_lines=1,
        max_chars=12,
        enabled=False,
    )

    assert len(clipped) == 12
    assert clipped.endswith("…")
