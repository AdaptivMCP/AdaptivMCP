# github_mcp/mcp_server/context.py
from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any, Optional

from github_mcp.utils import _extract_hostname, _render_external_hosts


# ------------------------------------------------------------------------------
# Request-scoped context (used for correlation/logging/dedupe)
# ------------------------------------------------------------------------------

REQUEST_MESSAGE_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_MESSAGE_ID", default=None)
REQUEST_SESSION_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_SESSION_ID", default=None)
REQUEST_CHATGPT_METADATA: ContextVar[Optional[dict[str, str]]] = ContextVar(
    "REQUEST_CHATGPT_METADATA", default=None
)

# End-to-end correlation identifier for each HTTP request.
# Derived from the incoming X-Request-Id header when present; otherwise generated server-side.
REQUEST_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_ID", default=None)

# These are imported by main.py in your repo; keep names stable.
REQUEST_PATH: ContextVar[Optional[str]] = ContextVar("REQUEST_PATH", default=None)
REQUEST_RECEIVED_AT: ContextVar[Optional[float]] = ContextVar("REQUEST_RECEIVED_AT", default=None)


def get_request_context() -> dict[str, Any]:
    return {
        "request_id": REQUEST_ID.get(),
        "path": REQUEST_PATH.get(),
        "received_at": REQUEST_RECEIVED_AT.get(),
        "session_id": REQUEST_SESSION_ID.get(),
        "message_id": REQUEST_MESSAGE_ID.get(),
        "chatgpt": REQUEST_CHATGPT_METADATA.get(),
    }


def get_request_id() -> Optional[str]:
    return REQUEST_ID.get()


# Explicit export list for stable imports in assistants and downstream tooling.
__all__ = [
    "REQUEST_ID",
    "REQUEST_MESSAGE_ID",
    "REQUEST_PATH",
    "REQUEST_RECEIVED_AT",
    "REQUEST_SESSION_ID",
    "REQUEST_CHATGPT_METADATA",
    "get_request_context",
    "get_request_id",
]


_CHATGPT_METADATA_HEADERS = {
    "x-openai-assistant-id": "assistant_id",
    "x-openai-conversation-id": "conversation_id",
    "x-openai-organization-id": "organization_id",
    "x-openai-project-id": "project_id",
    "x-openai-session-id": "session_id",
    "x-openai-user-id": "user_id",
}


def _extract_chatgpt_metadata(headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    """Extract safe ChatGPT metadata headers for logging and request context."""

    if not headers:
        return {}

    metadata: dict[str, str] = {}
    for raw_key, raw_val in headers:
        if not raw_key:
            continue
        key = raw_key.decode("utf-8", errors="ignore").strip().lower()
        mapped = _CHATGPT_METADATA_HEADERS.get(key)
        if not mapped:
            continue
        value = raw_val.decode("utf-8", errors="ignore").strip()
        if value:
            metadata[mapped] = value
    return metadata


# ------------------------------------------------------------------------------
# Dynamic write gate (environment-based)
# ------------------------------------------------------------------------------


def _parse_bool(value: Optional[str]) -> bool:
    v = (value or "").strip().lower()
    return v in ("1", "true", "t", "yes", "y", "on")


def _env_default_write_allowed() -> bool:
    # Matches your expectation: default true unless explicitly false
    return _parse_bool(os.environ.get("GITHUB_MCP_WRITE_ALLOWED", "true"))


class _WriteAllowedFlag:
    """
 Drop-in compatible:
 - bool(WRITE_ALLOWED)
 - WRITE_ALLOWED.value
 - WRITE_ALLOWED.value = True/False
 Uses the GITHUB_MCP_WRITE_ALLOWED environment variable as the sole source of truth.
 """

    def __init__(self) -> None:
        self._cache_value = _env_default_write_allowed()

    def __bool__(self) -> bool:
        return get_write_allowed()

    @property
    def value(self) -> bool:
        return get_write_allowed()

    @value.setter
    def value(self, approved: bool) -> None:
        set_write_allowed(bool(approved))


WRITE_ALLOWED = _WriteAllowedFlag()


def get_write_allowed(*, refresh_after_seconds: float = 0.5) -> bool:
    """
 Returns effective write gate based solely on GITHUB_MCP_WRITE_ALLOWED.
 refresh_after_seconds is ignored but kept for backwards compatibility.
 """
    del refresh_after_seconds
    val = _env_default_write_allowed()
    WRITE_ALLOWED._cache_value = val
    return val


def set_write_allowed(approved: bool) -> bool:
    """
 Updates the process environment variable used for write gating.
 """
    value = bool(approved)
    os.environ["GITHUB_MCP_WRITE_ALLOWED"] = "true" if value else "false"
    WRITE_ALLOWED._cache_value = value
    return value


def get_write_allowed_debug() -> dict[str, Any]:
    return {
        "value": get_write_allowed(refresh_after_seconds=0.0),
        "env_default": _env_default_write_allowed(),
        "cache": {
            "value": WRITE_ALLOWED._cache_value,
            "source": "env",
        },
    }


COMPACT_METADATA_DEFAULT = _parse_bool(
    os.environ.get("GITHUB_MCP_COMPACT_METADATA_DEFAULT", "true")
)
_TOOL_EXAMPLES: dict[str, Any] = {}
try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
    from mcp.server.transport_security import TransportSecuritySettings  # type: ignore

    FASTMCP_AVAILABLE = True

    def _normalize_allowed_hosts(hosts: list[str]) -> list[str]:
        normalized: list[str] = []
        for host in hosts:
            cleaned = _extract_hostname(host) or host.strip()
            if cleaned and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    def _expand_allowed_hosts(hosts: list[str]) -> list[str]:
        expanded: list[str] = []
        for host in hosts:
            if host not in expanded:
                expanded.append(host)
            if ":" not in host and not host.endswith(":*"):
                wildcard = f"{host}:*"
                if wildcard not in expanded:
                    expanded.append(wildcard)
        return expanded

    def _build_allowed_origins(hosts: list[str]) -> list[str]:
        origins: list[str] = []
        for host in hosts:
            if host.endswith(":*"):
                base_host = host[:-2]
                candidates = [f"http://{base_host}:*", f"https://{base_host}:*"]
            else:
                candidates = [f"http://{host}", f"https://{host}"]
            for origin in candidates:
                if origin not in origins:
                    origins.append(origin)
        return origins

    def _build_transport_security_settings() -> TransportSecuritySettings | None:
        allowed_hosts_env = os.getenv("ALLOWED_HOSTS")
        allowed_hosts = [
            host.strip() for host in (allowed_hosts_env or "").split(",") if host.strip()
        ]
        if "*" in allowed_hosts:
            return TransportSecuritySettings(enable_dns_rebinding_protection=False)

        for render_host in _render_external_hosts():
            if render_host not in allowed_hosts:
                allowed_hosts.append(render_host)

        normalized_hosts = _normalize_allowed_hosts(allowed_hosts)
        if not normalized_hosts:
            return None

        expanded_hosts = _expand_allowed_hosts(normalized_hosts)
        allowed_origins = _build_allowed_origins(expanded_hosts)
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=expanded_hosts,
            allowed_origins=allowed_origins,
        )

    mcp = FastMCP("github-mcp", transport_security=_build_transport_security_settings())
except Exception as exc:  # pragma: no cover - used when dependency missing
    FASTMCP_AVAILABLE = False
    missing_exc = exc

    class _MissingFastMCP:
        def tool(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("FastMCP import failed") from missing_exc

        def __getattr__(self, name: str) -> Any:
            raise AttributeError(name)

    mcp = _MissingFastMCP()
