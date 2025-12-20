"""Utilities for redacting secret-like strings from logs and outputs.

Design goals:
- Prevent accidental leakage of credentials or tokens.
- Avoid misleading placeholders that look like real token prefixes.
- Avoid triggering upstream redactors by emitting long secret-ish strings.

Note:
Some upstream/connector layers aggressively redact long hex/base64 strings. To
avoid confusing placeholders in user-visible logs, we proactively shorten common
non-secret identifiers (e.g., Git SHAs) before returning outputs.
"""

from __future__ import annotations

import re
from typing import Callable, Iterable


_REDACTED = "<redacted>"

# Common non-secret IDs we may see in outputs.
# - Git commit SHA: 40 hex
# - SHA-256: 64 hex
_SHA40_RE = re.compile(r"\b[0-9a-f]{40}\b", re.IGNORECASE)
_SHA64_RE = re.compile(r"\b[0-9a-f]{64}\b", re.IGNORECASE)


def _shorten_hex_ids(text: str) -> str:
    """Shorten long hex IDs to avoid triggering upstream token redaction."""

    def _short(m: re.Match[str]) -> str:
        s = m.group(0)
        # Keep enough to be useful for debugging while staying under common
        # redaction thresholds.
        return f"<sha:{s[:12]}>"

    text = _SHA40_RE.sub(_short, text)
    text = _SHA64_RE.sub(_short, text)
    return text


def _redact_tokenish(match: re.Match[str]) -> str:
    # Generic token-like matcher replacement.
    return _REDACTED


TOKEN_PATTERNS: list[tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]] = [
    (
        re.compile(r"https://x-access-token:([^@/\s]+)@github\.com/", re.IGNORECASE),
        "https://x-access-token:***@github.com/",
    ),
    (
        re.compile(r"x-access-token:([^@\s]+)@github\.com", re.IGNORECASE),
        "x-access-token:***@github.com",
    ),
    # GitHub tokens / PATs / similar
    (re.compile(r"\bgh[pous]_[A-Za-z0-9]{16,}\b", re.IGNORECASE), _REDACTED),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", re.IGNORECASE), _REDACTED),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b", re.IGNORECASE), _REDACTED),
    (re.compile(r"\bpat_[A-Za-z0-9_-]{20,}\b", re.IGNORECASE), _REDACTED),
    # OpenAI-style keys
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b", re.IGNORECASE), _REDACTED),
    # Render-ish tokens
    (re.compile(r"\b(?:r8c|r9c)[A-Za-z0-9_-]{20,}\b", re.IGNORECASE), _REDACTED),
    # AWS access keys
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), _REDACTED),
    # JWTs
    (
        re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "<redacted-jwt>",
    ),
    # Generic long base64/base64url-like strings
    (re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"), _redact_tokenish),
    (re.compile(r"\b[A-Za-z0-9_-]{64,}\b"), _redact_tokenish),
]


def redact_sensitive_text(text: str | None, extra_values: Iterable[str] | None = None) -> str:
    """Best-effort removal of tokens from arbitrary text."""

    if not text:
        return text or ""

    # Normalize any legacy placeholders from upstream layers.
    redacted = text.replace("<redacted-token>", _REDACTED)

    # Pre-shorten long hex IDs to avoid upstream redactors misclassifying them.
    redacted = _shorten_hex_ids(redacted)

    for pat, repl in TOKEN_PATTERNS:
        redacted = pat.sub(repl, redacted)  # type: ignore[arg-type]

    for value in extra_values or []:
        try:
            if value and isinstance(value, str):
                redacted = redacted.replace(value, "***")
        except Exception:
            # Best-effort; continue redacting other values.
            continue

    return redacted
