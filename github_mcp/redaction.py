"""Redaction utilities.

The MCP server should not emit secrets or quasi-identifiers in tool results.
This module provides conservative best-effort sanitization for:
  - auth tokens/headers
  - cookies
  - common secret-like strings
  - IP addresses (often treated as location-adjacent identifiers)

This is intentionally *not* a content filter; it is a safety layer to ensure
that accidental leaks from upstream services or subprocess output do not make
it into tool responses.
"""

from __future__ import annotations

import re
from typing import Any, Dict


_SENSITIVE_HEADER_KEYS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "set-cookie",
    "set-cookie2",
    "www-authenticate",
    "proxy-authenticate",
    # Location-like headers can expose internal endpoints or redirect targets.
    "location",
    "content-location",
    # Forwarding headers can carry client IPs.
    "x-forwarded-for",
    "forwarded",
    "x-real-ip",
    # Fingerprinting / device-ish
    "user-agent",
}


# Best-effort patterns. Keep these conservative to avoid mangling normal text.
_RE_EMAIL = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")
_RE_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_RE_GITHUB_PAT = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")
_RE_BASIC_AUTH = re.compile(r"Authorization:\s*Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE)
_RE_BEARER = re.compile(r"Authorization:\s*Bearer\s+[^\s\"']+", re.IGNORECASE)


def sanitize_headers(headers: Dict[str, Any] | None) -> Dict[str, Any]:
    """Remove sensitive headers entirely."""
    if not isinstance(headers, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in headers.items():
        if not isinstance(k, str):
            continue
        if k.lower() in _SENSITIVE_HEADER_KEYS:
            continue
        out[k] = v
    return out


def sanitize_text(text: Any) -> Any:
    """Redact common secret-ish patterns in a string; pass through otherwise."""
    if not isinstance(text, str):
        return text

    s = text
    # Redact explicit auth header fragments if they appear in logs.
    s = _RE_BASIC_AUTH.sub("Authorization: Basic [REDACTED]", s)
    s = _RE_BEARER.sub("Authorization: Bearer [REDACTED]", s)
    # Redact common GitHub tokens.
    s = _RE_GITHUB_PAT.sub("[REDACTED_GITHUB_TOKEN]", s)
    # Redact emails (often treated as identifiers).
    s = _RE_EMAIL.sub("[REDACTED_EMAIL]", s)
    # Redact IPv4 addresses (often treated as location-adjacent identifiers).
    s = _RE_IPV4.sub("[REDACTED_IP]", s)
    return s


def sanitize_obj(obj: Any) -> Any:
    """Recursively sanitize dict/list structures returned in tool payloads."""
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            # For nested header-like dicts, drop sensitive keys.
            if isinstance(k, str) and k.lower() == "headers" and isinstance(v, dict):
                out[k] = sanitize_headers(v)
                continue
            out[k] = sanitize_obj(v)
        return out

    if isinstance(obj, list):
        return [sanitize_obj(v) for v in obj]

    if isinstance(obj, tuple):
        return [sanitize_obj(v) for v in obj]

    if isinstance(obj, str):
        return sanitize_text(obj)

    return obj
