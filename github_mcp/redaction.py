"""Defense-in-depth redaction for secrets crossing output and logging boundaries.

This module deliberately uses conservative, secret-shaped patterns rather than
trying to identify every high-entropy string. It is intended as a last line of
defense: callers should still avoid placing credentials in tool results/logs.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDACTED = "<REDACTED_SECRET>"

_SECRET_KEY_RE = re.compile(
    r"(?i)(?:"
    r"access[_-]?token|api[_-]?key|auth(?:entication)?(?:$|[_-])|authorization|"
    r"bearer|client[_-]?secret|credential|gh[_-]?(?:token|pat)|"
    r"password|passwd|private[_-]?key|refresh[_-]?token|secret|token|"
    r"webhook[_-]?secret"
    r")"
)

_SECRET_ENV_NAME_RE = re.compile(
    r"(?i)^(?:"
    r"ADAPTIV_MCP_AUTH_TOKEN|MCP_AUTH_TOKEN|GITHUB_(?:TOKEN|PAT|OAUTH_TOKEN)|"
    r"GH_TOKEN|GH_PAT|GIT_HTTP_EXTRAHEADER|GIT_ASKPASS|SSH_ASKPASS|"
    r"RENDER_(?:API_KEY|API_TOKEN|TOKEN)"
    r")$"
)

# Provider/token formats that are recognizable without a surrounding key.
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])("
    r"(?:gh[pousr]_[A-Za-z0-9_]{20,})|"
    r"(?:github_pat_[A-Za-z0-9_]{20,})|"
    r"(?:github_vss_[A-Za-z0-9_]{20,})|"
    r"(?:glpat-[A-Za-z0-9_\-]{20,})"
    r")(?![A-Za-z0-9_])"
)

_BEARER_RE = re.compile(
    r"(?i)(\bBearer\s+)([^\s,;]+)"
)

_AUTH_HEADER_RE = re.compile(
    r"(?im)(\b(?:Authorization|Proxy-Authorization)\s*:\s*)"
    r"([^\r\n]+)"
)

_ENV_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:GITHUB_TOKEN|GH_TOKEN|GH_PAT|GIT_HTTP_EXTRAHEADER|"
    r"ADAPTIV_MCP_AUTH_TOKEN|MCP_AUTH_TOKEN|RENDER_API_KEY|RENDER_API_TOKEN|"
    r"RENDER_TOKEN)\s*=\s*)([^\s'\"]+)"
)

_CREDENTIAL_URL_RE = re.compile(
    r"(?P<prefix>https?://)(?P<userinfo>[^/@\s]+@)"
)

_GENERIC_LONG_SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?P<secret>[A-Za-z0-9+/=_\-]{48,})"
    r"(?![A-Za-z0-9])"
)


def _redact_string(value: str, *, key: str | None = None) -> str:
    """Redact known credential forms and values associated with secret keys."""

    if not value:
        return value

    # Secret-bearing mapping keys are authoritative: redact the whole value
    # rather than trying to partially preserve it.
    if key and (_SECRET_KEY_RE.search(key) or _SECRET_ENV_NAME_RE.fullmatch(key)):
        return REDACTED

    out = value

    def _redact_auth_header(match: re.Match[str]) -> str:
        prefix = match.group(1)
        raw_value = match.group(2)
        scheme, separator, _credential = raw_value.partition(" ")
        if separator and scheme.lower() == "bearer":
            return prefix + "Bearer " + REDACTED
        return prefix + REDACTED

    out = _AUTH_HEADER_RE.sub(_redact_auth_header, out)
    out = _BEARER_RE.sub(lambda m: m.group(1) + REDACTED, out)
    out = _ENV_ASSIGNMENT_RE.sub(lambda m: m.group(1) + REDACTED, out)
    out = _CREDENTIAL_URL_RE.sub(lambda m: m.group("prefix") + REDACTED + "@", out)
    out = _TOKEN_RE.sub(REDACTED, out)

    # Only redact generic long strings when they have strong secret-like
    # characteristics. This avoids destroying ordinary source code, hashes,
    # commit IDs, and user data merely because they are long.
    def _generic(match: re.Match[str]) -> str:
        candidate = match.group("secret")
        # Paths and hexadecimal object IDs are ordinary workspace metadata.
        if (
            candidate.startswith(("/", "./", "../"))
            and candidate.count("/") >= 2
            and "=" not in candidate
        ) or re.fullmatch(r"[0-9a-fA-F]+", candidate):
            return candidate
        if (
            any(ch.isalpha() for ch in candidate)
            and any(ch.isdigit() for ch in candidate)
            and ("=" in candidate or len(candidate) >= 64)
        ):
            return REDACTED
        return candidate

    return _GENERIC_LONG_SECRET_RE.sub(_generic, out)


def redact_any(value: Any, *, key: str | None = None) -> Any:
    """Return a recursively redacted copy suitable for client output/logging.

    Redaction is best-effort and fail-closed for secret-bearing mapping keys.
    Unknown objects are converted only when their string representation is
    necessary; otherwise their original value is preserved.
    """

    try:
        if isinstance(value, str):
            return _redact_string(value, key=key)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, bytes | bytearray):
            return "<REDACTED_BYTES>"
        if isinstance(value, Mapping):
            return {
                str(k): redact_any(v, key=str(k))
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [redact_any(v, key=key) for v in value]
        if isinstance(value, tuple):
            return tuple(redact_any(v, key=key) for v in value)
        if isinstance(value, set):
            return {redact_any(v, key=key) for v in value}
        return _redact_string(str(value), key=key)
    except Exception:
        # Never let redaction become a new data-leak path. If an unexpected
        # object cannot be traversed safely, expose only a fixed marker.
        return REDACTED


def redact_url(value: str) -> str:
    """Redact credentials from a URL while preserving its normal structure."""

    if not isinstance(value, str):
        return value
    try:
        parts = urlsplit(value)
        if parts.username is None and parts.password is None:
            return _redact_string(value)
        host = parts.hostname or ""
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        netloc = f"{REDACTED}@{host}"
        if parts.port is not None:
            netloc += f":{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        return _redact_string(value)


__all__ = ["REDACTED", "redact_any", "redact_url"]
