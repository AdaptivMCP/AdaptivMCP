"""Path/prefix helpers for HTTP routes.

These utilities centralize logic for normalizing reverse-proxy prefixes and
deriving stable base paths from Starlette requests. Multiple routes need to
compute a "base path" to build self-referential URLs; consolidating the logic
reduces drift and avoids subtle inconsistencies.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def normalize_base_path(base_path: str | None) -> str:
    """Normalize a URL base path.

    Returns either:
    - "" (empty string) when no prefix applies, or
    - a string starting with a single leading slash and no trailing slash.
    """

    if not base_path:
        return ""
    cleaned = base_path.strip()
    if cleaned in {"", "/"}:
        return ""
    return "/" + cleaned.strip("/")


def request_base_path(request: Any, suffixes: Iterable[str]) -> str:
    """Best-effort derivation of a base path for the current request.

    Resolution order:
    1) forwarded prefix headers
    2) strip a known suffix from request.url.path
    3) request.scope['root_path']
    """

    # Starlette provides a case-insensitive Headers mapping.
    headers = getattr(request, "headers", None) or {}
    hdr_prefix = "x-forwarded-" + "prefix"
    hdr_path = "x-forwarded-" + "path"
    forwarded_prefix = headers.get(hdr_prefix) or headers.get(hdr_path)
    if forwarded_prefix:
        return normalize_base_path(forwarded_prefix)

    url = getattr(request, "url", None)
    path = getattr(url, "path", "") if url is not None else ""
    path = path or ""
    for suffix in suffixes:
        if suffix and path.endswith(suffix):
            candidate = path[: -len(suffix)]
            return normalize_base_path(candidate)

    scope = getattr(request, "scope", None)
    root_path = scope.get("root_path") if isinstance(scope, dict) else None
    return normalize_base_path(root_path)


__all__ = [
    "normalize_base_path",
    "request_base_path",
]
