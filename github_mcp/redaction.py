"""Utilities for redacting token-like secrets from logs and outputs."""

from __future__ import annotations

import re
from typing import Iterable


TOKEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"https://x-access-token:([^@/\s]+)@github\.com/", re.IGNORECASE),
        "https://x-access-token:***@github.com/",
    ),
    (
        re.compile(r"x-access-token:([^@\s]+)@github\.com", re.IGNORECASE),
        "x-access-token:***@github.com",
    ),
    (re.compile(r"\bgh[pous]_[A-Za-z0-9]{16,}\b", re.IGNORECASE), "gh***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", re.IGNORECASE), "github_pat_***"),
    (re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b", re.IGNORECASE), "glpat-***"),
    (re.compile(r"\bpat_[A-Za-z0-9_-]{20,}\b", re.IGNORECASE), "pat_***"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b", re.IGNORECASE), "sk-***"),
    (re.compile(r"\b(?:r8c|r9c)[A-Za-z0-9_-]{20,}\b", re.IGNORECASE), "r8c***"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), "***"),
    (
        re.compile(r"\b[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "<redacted-jwt>",
    ),
    (
        re.compile(r"\b[a-zA-Z0-9+/]{40,}={0,2}\b"),
        "<redacted-token>",
    ),
    (
        re.compile(r"\b[a-zA-Z0-9_-]{64,}\b"),
        "<redacted-token>",
    ),
]


def redact_sensitive_text(text: str | None, extra_values: Iterable[str] | None = None) -> str:
    """Best-effort removal of tokens from arbitrary text.

    The patterns intentionally err on the side of redaction to prevent secret
    leakage in logs, tool responses, or OpenAI connector payloads.
    """

    if not text:
        return text or ""

    redacted = text
    for pat, repl in TOKEN_PATTERNS:
        redacted = pat.sub(repl, redacted)

    for value in extra_values or []:
        try:
            if value and isinstance(value, str):
                redacted = redacted.replace(value, "***")
        except Exception:
            # Best-effort; continue redacting other values.
            continue

    return redacted
