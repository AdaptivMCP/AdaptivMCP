"""Handle parsing utilities.

This module exists to normalize and interpret user-provided "handles" (e.g., #123,
URLs, or other identifiers) used by higher-level tools.

Design goals
- No regex usage.
- Minimal pre-validation. typical passing values through to downstream APIs.
- Best-effort extraction of numeric issue/PR IDs from common formats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParsedHandle:
    raw: str
    number: Optional[int]
    # The canonical "handle" form we surface in tool outputs.
    canonical: str


def _strip(s: Optional[str]) -> str:
    return (s or "").strip()


def _extract_trailing_int(text: str) -> Optional[int]:
    """Extract a trailing integer from the string without regex.

    Examples:
    - "#123" -> 123
    - ".../issues/123" -> 123
    - "123" -> 123
    - "abc" -> None

    This is intentionally permissive: it scans from the end and consumes digits
    until the first non-digit.
    """

    if not text:
        return None

    i = len(text) - 1
    while i >= 0 and text[i].isdigit():
        i -= 1

    # No trailing digits
    if i == len(text) - 1:
        return None

    digits = text[i + 1 :]
    try:
        return int(digits)
    except Exception:
        return None


def parse_handle(handle: Optional[str]) -> ParsedHandle:
    """Parse a user-provided handle into a best-effort numeric ID.

    Accepted examples (best-effort):
    - "#123" / "123"
    - "issue #123"
    - "https://github.com/org/repo/issues/123"
    - "https://github.com/org/repo/pull/123"

    Notes:
    - If a number cannot be derived, number=None.
    - canonical is returned as "#<number>" when number is known, otherwise
    the stripped raw input.
    """

    raw = _strip(handle)
    if not raw:
        return ParsedHandle(raw="", number=None, canonical="")

    # Fast path: '#<digits>'
    if raw.startswith("#"):
        digits = raw[1:].strip()
        if digits.isdigit():
            n = int(digits)
            return ParsedHandle(raw=raw, number=n, canonical=f"#{n}")

    # Plain digits
    if raw.isdigit():
        n = int(raw)
        return ParsedHandle(raw=raw, number=n, canonical=f"#{n}")

    # URLs or other strings: attempt to extract trailing int
    n = _extract_trailing_int(raw)
    if n is not None:
        return ParsedHandle(raw=raw, number=n, canonical=f"#{n}")

    return ParsedHandle(raw=raw, number=None, canonical=raw)


def coerce_issue_or_pr_number(handle: Optional[str]) -> Optional[int]:
    """Return a numeric issue/PR number if it can be inferred, else None."""

    return parse_handle(handle).number
