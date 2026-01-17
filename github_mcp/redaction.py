"""Secret redaction utilities.

This repository is often run inside LLM connector environments. In those
contexts, returning raw secret material (tokens, API keys) in tool outputs or
error payloads can cause upstream safety systems to block the response.

These helpers implement conservative, best-effort redaction for common secret
formats while minimizing false positives.

Redaction can be disabled via:
  GITHUB_MCP_REDACT_SECRETS=0
"""

from __future__ import annotations

import os
import re
from typing import Any


def _env_flag(name: str, *, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


REDACT_SECRETS = _env_flag("GITHUB_MCP_REDACT_SECRETS", default=True)


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # GitHub tokens
    (re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b"), "<REDACTED_GITHUB_TOKEN>"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "<REDACTED_GITHUB_TOKEN>"),
    # Slack tokens
    (re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"), "<REDACTED_SLACK_TOKEN>"),
    (re.compile(r"\bxapp-[A-Za-z0-9-]{10,}\b"), "<REDACTED_SLACK_TOKEN>"),
    # AWS access key id
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "<REDACTED_AWS_ACCESS_KEY_ID>"),
    # Render tokens (approximate)
    (
        re.compile(r"\b(rndr_[A-Za-z0-9]{20,}|render_[A-Za-z0-9]{20,})\b", re.IGNORECASE),
        "<REDACTED_RENDER_TOKEN>",
    ),
]

# Generic high-entropy-ish token: 32+ characters, mostly urlsafe/base64-ish.
# IMPORTANT: Avoid blanket redaction of all long strings when a single "token" word
# appears elsewhere in the payload (this caused over-redaction of SHAs, IDs, etc.).
# Instead, only redact long values that are *directly* associated with a key context.
_GENERIC_TOKEN = r"[A-Za-z0-9_\-]{32,}"

_KEY_VALUE_CONTEXTUAL = re.compile(
    rf"(?i)(\b(?:token|secret|api[_-]?key|password|passwd|private[_-]?key)\b\s*[:=]\s*)(['\"]?){_GENERIC_TOKEN}(\2)"
)
_AUTH_BEARER_CONTEXTUAL = re.compile(rf"(?i)(\bauthorization\b\s*[:=]\s*bearer\s+){_GENERIC_TOKEN}")
_BEARER_TOKEN_CONTEXTUAL = re.compile(rf"(?i)(\bbearer\s+){_GENERIC_TOKEN}")


def redact_text(text: str) -> str:
    """Redact common secrets from an arbitrary string."""

    if not REDACT_SECRETS:
        return text
    if not isinstance(text, str) or not text:
        return text

    out = text
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)

    # Contextual generic redaction: only redact values that are directly tied
    # to an obvious secret-bearing key or Authorization/Bearer token.
    out = _KEY_VALUE_CONTEXTUAL.sub(r"\1\2<REDACTED_TOKEN>\3", out)
    out = _AUTH_BEARER_CONTEXTUAL.sub(r"\1<REDACTED_TOKEN>", out)
    out = _BEARER_TOKEN_CONTEXTUAL.sub(r"\1<REDACTED_TOKEN>", out)

    return out


def redact_any(value: Any, *, max_depth: int = 6, _depth: int = 0) -> Any:
    """Recursively redact secrets in nested dict/list structures."""

    if not REDACT_SECRETS:
        return value

    if _depth > max_depth:
        return value

    if isinstance(value, str):
        return redact_text(value)

    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            out[k] = redact_any(v, max_depth=max_depth, _depth=_depth + 1)
        return out

    if isinstance(value, (list, tuple)):
        seq = [redact_any(v, max_depth=max_depth, _depth=_depth + 1) for v in value]
        return seq if isinstance(value, list) else tuple(seq)

    return value
