"""Retry and backoff helpers shared across GitHub MCP modules."""

from __future__ import annotations

import os
import random


def jitter_sleep_seconds(
    delay_seconds: float,
    *,
    respect_min: bool = True,
    cap_seconds: float = 1.0,
) -> float:
    """Return a jittered sleep duration.

    Jitter reduces synchronized retry storms across concurrent clients.

    When ``respect_min`` is True (e.g. Retry-After/X-RateLimit-Reset driven delays),
    jitter is added *after* the minimum delay so retries do not happen early.

    ``cap_seconds`` caps the additive jitter when ``respect_min`` is True.
    """

    try:
        delay = float(delay_seconds)
    except Exception:
        return 0.0

    if delay <= 0:
        return 0.0

    # Keep tests deterministic.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return delay

    if respect_min:
        cap = 0.0
        try:
            cap = float(cap_seconds)
        except Exception:
            cap = 0.0
        cap = max(0.0, cap)
        return delay + random.uniform(0.0, min(cap, delay * 0.25))

    # "Full jitter" for exponential backoff.
    return random.uniform(0.0, delay)


__all__ = ["jitter_sleep_seconds"]
