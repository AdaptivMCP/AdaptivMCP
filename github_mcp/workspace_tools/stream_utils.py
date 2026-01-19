"""Utilities for normalizing and summarizing command output streams.

We intentionally keep these helpers tiny and dependency-free because they are
used in both tool payload shaping and log rendering.
"""

from __future__ import annotations


def normalize_stream_text(text: str) -> str:
    """Normalize newlines for stable rendering.

    Some commands emit carriage returns ("\r") for progress bars. These can
    render poorly when stored in JSON or line-oriented log backends.
    """

    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_stats(text: str) -> tuple[int, int]:
    """Return (chars, lines) for the provided text after normalization."""

    normalized = normalize_stream_text(text or "")
    if not normalized:
        return (0, 0)
    return (len(normalized), normalized.count("\n") + 1)
