"""HTTP utilities shared across connector integrations."""

from __future__ import annotations

import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from collections.abc import Iterable, Mapping
from typing import Any


def build_response_payload(resp: Any, *, body: Any | None = None) -> dict[str, Any]:
    """Build a stable response payload.

    This helper intentionally accepts a duck-typed response object so it can be
    reused in multiple integration clients without creating import cycles.
    """

    payload: dict[str, Any] = {
        "status_code": getattr(resp, "status_code", None),
        "headers": dict(getattr(resp, "headers", {}) or {}),
    }
    if body is not None:
        payload["json"] = body
    else:
        payload["text"] = getattr(resp, "text", "")
    return payload


def extract_response_json(resp: Any) -> Any | None:
    """Best-effort JSON body extraction.

    Returns None when the response does not contain JSON or parsing fails.
    """

    headers = getattr(resp, "headers", {}) or {}
    content_type = str(headers.get("content-type", "")).lower()
    if content_type and "json" not in content_type:
        return None

    json_method = getattr(resp, "json", None)
    if not callable(json_method):
        return None
    try:
        return json_method()
    except Exception as exc:
        _ = exc
        return None


def parse_rate_limit_delay_seconds(
    resp: Any,
    *,
    reset_header_names: Iterable[str],
    allow_epoch_millis: bool = False,
    allow_duration_seconds: bool = False,
    now: float | None = None,
) -> float | None:
    """Parse a retry delay from standard rate-limit headers.

    Order of precedence:
    1) Retry-After (seconds)
    2) Reset headers (names provided by caller)

    Some APIs return epoch seconds (or milliseconds). Others return a duration.
    Callers control which variants are allowed.
    """

    headers: Mapping[str, str] = getattr(resp, "headers", {}) or {}

    def _get_header(name: str) -> str | None:
        value = headers.get(name)
        if value is not None:
            return value
        lowered = name.lower()
        for key, header_value in headers.items():
            if key.lower() == lowered:
                return header_value
        return None

    retry_after = _get_header("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(retry_after)
            except (TypeError, ValueError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if now is None:
                now = time.time()
            return max(0.0, parsed.timestamp() - now)

    reset_header: str | None = None
    for name in reset_header_names:
        candidate = _get_header(name)
        if candidate is None:
            continue
        candidate_str = str(candidate).strip()
        if not candidate_str:
            continue
        reset_header = candidate_str
        break

    if not reset_header:
        return None

    try:
        raw = float(reset_header)
    except ValueError:
        return None

    if now is None:
        now = time.time()

    # Epoch milliseconds.
    if allow_epoch_millis and raw > 10_000_000_000:
        return max(0.0, (raw / 1000.0) - now)

    # Epoch seconds.
    if raw > 1_000_000_000:
        return max(0.0, raw - now)

    # Duration seconds.
    if allow_duration_seconds:
        return max(0.0, raw)

    return None


__all__ = [
    "build_response_payload",
    "extract_response_json",
    "parse_rate_limit_delay_seconds",
]
