"""Privacy helpers for sanitizing metadata.

This module centralizes lightweight privacy filters so we can guarantee that
server-generated metadata never includes sensitive user details such as
location information.
"""

from __future__ import annotations

from typing import Any, Mapping


def strip_location_metadata(meta: Mapping[str, Any] | None) -> dict[str, Any]:
    """Remove any metadata keys that could reveal user location.

    The incoming metadata may originate from upstream clients. We defensively
    strip any keys that hint at geographic details or timezones to avoid
    surfacing them to tools.
    """

    cleaned: dict[str, Any] = dict(meta or {})
    for key in list(cleaned.keys()):
        key_l = str(key).lower()
        if "location" in key_l or "timezone" in key_l:
            cleaned.pop(key, None)

    return cleaned


__all__ = ["strip_location_metadata"]
