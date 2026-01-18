"""Small utilities for generating and colorizing unified diffs.

These are used primarily for Render log readability. Keep this module dependency-light
and easy to unit test.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import unified_diff

ANSI_RESET = "\x1b[0m"
ANSI_RED = "\x1b[31m"
ANSI_GREEN = "\x1b[32m"
ANSI_CYAN = "\x1b[36m"
ANSI_DIM = "\x1b[2m"


@dataclass(frozen=True)
class DiffStats:
    added: int
    removed: int


def sha1_8(text: str) -> str:
    """Return a stable 8-hex digest for text.

    Historically this function used SHA-1. We keep the public name for
    backwards compatibility but use BLAKE2s to avoid insecure hashing
    primitives while preserving the short, deterministic output.
    """

    # 4 bytes -> 8 hex characters.
    return hashlib.blake2s(text.encode("utf-8", errors="replace"), digest_size=4).hexdigest()


def build_unified_diff(
    before: str,
    after: str,
    *,
    fromfile: str = "before",
    tofile: str = "after",
    n: int = 3,
) -> str:
    """Return a unified diff (as a single string) for two text blobs."""

    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)

    lines = unified_diff(
        before_lines,
        after_lines,
        fromfile=fromfile,
        tofile=tofile,
        n=n,
        lineterm="",
    )
    return "\n".join(lines)


def diff_stats(diff_text: str) -> DiffStats:
    """Count added/removed lines in a unified diff."""

    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if not line:
            continue
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return DiffStats(added=added, removed=removed)


def colorize_unified_diff(diff_text: str) -> str:
    """Colorize a unified diff using ANSI.

    - additions: green
    - deletions: red
    - hunk headers: cyan
    - file headers: dim
    """

    if not diff_text:
        return diff_text

    out: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            out.append(f"{ANSI_DIM}{line}{ANSI_RESET}")
        elif line.startswith("@@"):
            out.append(f"{ANSI_CYAN}{line}{ANSI_RESET}")
        elif line.startswith("+"):
            out.append(f"{ANSI_GREEN}{line}{ANSI_RESET}")
        elif line.startswith("-"):
            out.append(f"{ANSI_RED}{line}{ANSI_RESET}")
        else:
            out.append(line)

    return "\n".join(out)
