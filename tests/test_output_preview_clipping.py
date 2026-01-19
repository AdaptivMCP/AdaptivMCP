from __future__ import annotations

import github_mcp.mcp_server.decorators as dec


def test_format_stream_block_keeps_tail_context() -> None:
    text = "\n".join([f"line-{i}" for i in range(1, 9)])
    block = dec._format_stream_block(
        text,
        label="stdout",
        header_color=dec.ANSI_GREEN,
        max_lines=4,
        max_chars=2000,
    )

    assert "line-1" in block
    assert "line-8" in block
    assert "line-3" not in block
    assert "… (" in block


def test_clip_text_preserves_tail_chars() -> None:
    text = ("A" * 100) + "TAILXYZ"
    clipped = dec._clip_text(
        text,
        max_lines=1,
        max_chars=60,
        enabled=False,
    )

    assert "TAILXYZ" in clipped
