"""Explicit HTTP authentication and principal binding for MCP transport."""
from __future__ import annotations

import hashlib
import hmac
import os
import re
from collections.abc import Iterable
from typing import Any

from starlette.responses import JSONResponse, Response

AUTH_TOKEN_ENV_VARS = ("ADAPTIV_MCP_AUTH_TOKEN", "MCP_AUTH_TOKEN")
CAPABILITY_ENV = "ADAPTIV_MCP_AUTH_CAPABILITIES"
PUBLIC_PATH_PREFIXES = ("/healthz", "/static/")
PUBLIC_PATHS = {
    "/",
    "/favicon.ico",
    "/robots.txt",
}


def _configured_auth_token() -> str | None:
    for name in AUTH_TOKEN_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _configured_capabilities() -> frozenset[str]:
    raw = os.environ.get(CAPABILITY_ENV, "")
    return frozenset(
        item.strip()
        for item in re.split(r"[,\\s]+", raw)
        if item.strip()
    )


def _token_principal(token: str) -> str:
    """Return a non-secret stable principal derived from the credential."""
    return "token:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def _authorization_token(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
    for key, value in headers:
        if (key or b"").lower() != b"authorization":
            continue
        raw = (value or b"").decode("utf-8", errors="ignore").strip()
        scheme, separator, credential = raw.partition(" ")
        if separator and scheme.lower() == "bearer" and credential.strip():
            return credential.strip()
        return None
    return None


def authenticate_request(
    headers: Iterable[tuple[bytes, bytes]],
) -> tuple[bool, str | None, frozenset[str]]:
    """Validate the configured bearer credential and return principal/capabilities."""
    expected = _configured_auth_token()
    if expected is None:
        return False, None, frozenset()

    presented = _authorization_token(headers)
    if presented is None or not hmac.compare_digest(presented, expected):
        return False, None, frozenset()

    return True, _token_principal(expected), _configured_capabilities()


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def authentication_error(*, configuration_error: bool = False) -> Response:
    if configuration_error:
        return JSONResponse(
            {"error": "transport_auth_not_configured"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        {"error": "unauthorized"},
        status_code=401,
        headers={
            "Cache-Control": "no-store",
            "WWW-Authenticate": 'Bearer realm="adaptiv-mcp"',
        },
    )


def auth_configuration_present() -> bool:
    return _configured_auth_token() is not None


__all__ = [
    "AUTH_TOKEN_ENV_VARS",
    "CAPABILITY_ENV",
    "authenticate_request",
    "auth_configuration_present",
    "authentication_error",
    "is_public_path",
]
