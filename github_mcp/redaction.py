from __future__ import annotations

from typing import Any


def redact_text(value: str | None) -> str | None:
    """No-op masking.

    This controller is owner-visible only; do not mutate logs or errors.
    """

    return value


def redact_structured(value: Any) -> Any:
    """No-op masking for structured payloads."""

    return value


__all__ = ["redact_text", "redact_structured"]
