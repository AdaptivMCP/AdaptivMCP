# github_mcp/mcp_server/context.py
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from typing import Any, Optional

from mcp.server.transport_security import TransportSecuritySettings

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


# Explicit export list for stable imports in clients and downstream tooling.
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
# Environment helpers
# ------------------------------------------------------------------------------


def _parse_bool(value: Optional[str]) -> bool:
    v = (value or "").strip().lower()
    return v in ("1", "true", "t", "yes", "y", "on")


class _WriteAllowedFlag:
    """
    Drop-in compatible:
    - bool(WRITE_ALLOWED)
    - WRITE_ALLOWED.value
    - WRITE_ALLOWED.value = True/False

    Compatibility shim: write approval is treated as enabled.
    """

    def __init__(self) -> None:
        self._cache_value = True

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
    Compatibility shim returning True.

    refresh_after_seconds is ignored but kept for backwards compatibility.
    """
    del refresh_after_seconds
    WRITE_ALLOWED._cache_value = True
    return True


def set_write_allowed(approved: bool) -> bool:
    """
    Compatibility shim for legacy callers.
    """
    del approved
    WRITE_ALLOWED._cache_value = True
    return True


def get_write_allowed_debug() -> dict[str, Any]:
    return {
        "value": get_write_allowed(refresh_after_seconds=0.0),
        "cache": {
            "value": WRITE_ALLOWED._cache_value,
            "source": "static",
        },
    }


COMPACT_METADATA_DEFAULT = _parse_bool(
    os.environ.get("GITHUB_MCP_COMPACT_METADATA_DEFAULT", "true")
)
_TOOL_EXAMPLES: dict[str, Any] = {}


def _split_host_list(value: str | None) -> list[str]:
    if not value:
        return []
    parts = re.split(r"[,\s]+", value)
    return [part.strip() for part in parts if part.strip()]


def _resolve_transport_security() -> TransportSecuritySettings | None:
    host_inputs = _split_host_list(os.environ.get("ALLOWED_HOSTS"))
    host_inputs.extend(_render_external_hosts())

    base_hosts: list[str] = []
    for host in host_inputs:
        hostname = _extract_hostname(host) or host
        hostname = hostname.strip().lower()
        if hostname and hostname not in base_hosts:
            base_hosts.append(hostname)

    if not base_hosts:
        return None

    allowed_hosts: list[str] = []
    allowed_origins: list[str] = []
    for hostname in base_hosts:
        allowed_hosts.extend([hostname, f"{hostname}:*"])
        for scheme in ("http", "https"):
            allowed_origins.extend([f"{scheme}://{hostname}", f"{scheme}://{hostname}:*"])

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


try:
    from mcp.server.fastmcp import FastMCP  # type: ignore

    FASTMCP_AVAILABLE = True

    mcp = FastMCP(
        "github-mcp",
        host=os.environ.get("FASTMCP_HOST", "0.0.0.0"),
        transport_security=_resolve_transport_security(),
    )
except Exception as exc:  # pragma: no cover - used when dependency missing
    FASTMCP_AVAILABLE = False
    missing_exc = exc

    class _MissingFastMCP:
        def tool(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("FastMCP import failed") from missing_exc

        def __getattr__(self, name: str) -> Any:
            raise AttributeError(name)

    mcp = _MissingFastMCP()
