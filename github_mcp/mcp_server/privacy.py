"""Privacy helpers for sanitizing metadata.

This module centralizes lightweight privacy filters so we can guarantee that
server-generated metadata never includes sensitive user details such as
location information or client IP addresses.
"""

from __future__ import annotations

import ipaddress
from typing import Any, Mapping


_IP_HINT_TOKENS = (
    "ip",
    "clientip",
    "client_ip",
    "ip_address",
    "ipaddress",
    "remote_addr",
    "x-forwarded-for",
)


def _looks_like_ip(value: Any) -> bool:
    """Return True if the value resembles an IPv4/IPv6 address string."""

    if not isinstance(value, str):
        return False

    candidate = value.strip()
    if not candidate:
        return False

    try:
        ipaddress.ip_address(candidate.split(",")[0].strip())
        return True
    except Exception:
        return False


def strip_location_metadata(meta: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove any metadata keys that could reveal user location or IP address.

    The incoming metadata may originate from upstream clients. We defensively
    strip any keys that hint at geographic details, timezones, or client IPs to
    avoid surfacing them to tools.
    """

    cleaned: dict[str, Any] = dict(meta or {})
    for key in list(cleaned.keys()):
        key_l = str(key).lower()
        value = cleaned.get(key)

        if "location" in key_l or "timezone" in key_l:
            cleaned.pop(key, None)
            continue

        if any(tok in key_l for tok in _IP_HINT_TOKENS) or _looks_like_ip(value):
            cleaned.pop(key, None)

    return cleaned


__all__ = ["strip_location_metadata"]
