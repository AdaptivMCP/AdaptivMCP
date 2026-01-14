"""HTTP utilities shared across connector integrations."""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Mapping, Optional


def build_response_payload(resp: Any, *, body: Any | None = None) -> Dict[str, Any]:
    """Build a stable response payload.

    This helper intentionally accepts a duck-typed response object so it can be
    reused in multiple integration clients without creating import cycles.
    """

    payload: Dict[str, Any] = {
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

    json_method = getattr(resp, "json", None)
    if not callable(json_method):
        return None
    try:
        return json_method()
    except Exception:
        return None


def parse_rate_limit_delay_seconds(
    resp: Any,
    *,
    reset_header_names: Iterable[str],
    allow_epoch_millis: bool = False,
    allow_duration_seconds: bool = False,
    now: Optional[float] = None,
) -> float | None:
    """Parse a retry delay from standard rate-limit headers.

    Order of precedence:
    1) Retry-After (seconds)
    2) Reset headers (names provided by caller)

    Some APIs return epoch seconds (or milliseconds). Others return a duration.
    Callers control which variants are allowed.
    """

    headers: Mapping[str, str] = getattr(resp, "headers", {}) or {}

    retry_after = headers.get("Retry-After")
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None

    reset_header: str | None = None
    for name in reset_header_names:
        candidate = headers.get(name)
        if candidate:
            reset_header = candidate
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
