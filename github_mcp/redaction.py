from __future__ import annotations

import re
from typing import Any


_CREDENTIAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # GitHub tokens (classic + fine-grained)
    (re.compile(r"https://x-access-token:[^@/\s]+@github\.com/"), "https://x-access-token:***@github.com/"),
    (re.compile(r"x-access-token:[^@\s]+@github\.com"), "x-access-token:***@github.com"),
    (re.compile(r"\bgh[pous]_[A-Za-z0-9]{20,}\b"), "gh*_***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "github_pat_***"),
    # JWT / structured tokens
    (re.compile(r"\b[A-Za-z0-9_-]{20,}\.([A-Za-z0-9._-]{10,})\.([A-Za-z0-9._-]{10,})\b"), "***.***.***"),
    # Render / API style tokens
    (re.compile(r"\b(?:rndr|render)[A-Za-z0-9_-]{16,}\b", re.IGNORECASE), "render_token_***"),
    # Generic bearer/API tokens
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-+/]{20,}\b", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"\b[A-Za-z0-9]{32,}\b"), "***"),
)


def redact_text(value: str | None) -> str | None:
    if not isinstance(value, str):
        return value
    redacted = value
    for pattern, repl in _CREDENTIAL_PATTERNS:
        redacted = pattern.sub(repl, redacted)
    return redacted


def redact_structured(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_structured(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        coerced = [redact_structured(v) for v in value]
        return type(value)(coerced) if not isinstance(value, set) else set(coerced)
    return value


__all__ = ["redact_text", "redact_structured"]
