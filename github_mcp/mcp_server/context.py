# github_mcp/mcp_server/context.py
from __future__ import annotations

import os
import re
from contextvars import ContextVar
from typing import Any

try:
    # Optional dependency: FastMCP and its transport security helpers.
    from mcp.server.transport_security import TransportSecuritySettings
except Exception:  # pragma: no cover
    TransportSecuritySettings = None  # type: ignore[assignment]


# ------------------------------------------------------------------------------
# Request-scoped context (used for correlation/logging/dedupe)
# ------------------------------------------------------------------------------

REQUEST_MESSAGE_ID: ContextVar[str | None] = ContextVar("REQUEST_MESSAGE_ID", default=None)
REQUEST_SESSION_ID: ContextVar[str | None] = ContextVar("REQUEST_SESSION_ID", default=None)
# Optional idempotency/dedupe keys for correlating retries across transport boundaries.
# These are intentionally kept separate from REQUEST_ID (per-HTTP-request) and
# MESSAGE_ID (per JSON-RPC message) because upstream clients may choose to
# retry a request with a new request id but the same idempotency key.
REQUEST_IDEMPOTENCY_KEY: ContextVar[str | None] = ContextVar(
    "REQUEST_IDEMPOTENCY_KEY", default=None
)
REQUEST_CHATGPT_METADATA: ContextVar[dict[str, str] | None] = ContextVar(
    "REQUEST_CHATGPT_METADATA", default=None
)

# End-to-end correlation identifier for each HTTP request.
# Derived from the incoming X-Request-Id header when present; otherwise generated server-side.
REQUEST_ID: ContextVar[str | None] = ContextVar("REQUEST_ID", default=None)

# These are imported by main.py in your repo; keep names stable.
REQUEST_PATH: ContextVar[str | None] = ContextVar("REQUEST_PATH", default=None)
REQUEST_RECEIVED_AT: ContextVar[float | None] = ContextVar("REQUEST_RECEIVED_AT", default=None)


def get_request_context() -> dict[str, Any]:
    return {
        "request_id": REQUEST_ID.get(),
        "path": REQUEST_PATH.get(),
        "received_at": REQUEST_RECEIVED_AT.get(),
        "session_id": REQUEST_SESSION_ID.get(),
        "message_id": REQUEST_MESSAGE_ID.get(),
        "idempotency_key": REQUEST_IDEMPOTENCY_KEY.get(),
        "chatgpt": REQUEST_CHATGPT_METADATA.get(),
    }


def get_request_id() -> str | None:
    return REQUEST_ID.get()


# Explicit export list for stable imports in clients and downstream tooling.
__all__ = [
    "REQUEST_ID",
    "REQUEST_MESSAGE_ID",
    "REQUEST_PATH",
    "REQUEST_RECEIVED_AT",
    "REQUEST_SESSION_ID",
    "REQUEST_IDEMPOTENCY_KEY",
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


def _parse_bool(value: str | None) -> bool:
    v = (value or "").strip().lower()
    return v in ("1", "true", "t", "yes", "y", "on")


class _WriteAllowedFlag:
    """Drop-in compatible:
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
    """Compatibility shim returning True.

    refresh_after_seconds is ignored but kept for backwards compatibility.
    """
    del refresh_after_seconds
    WRITE_ALLOWED._cache_value = True
    return True


def set_write_allowed(approved: bool) -> bool:
    """Compatibility shim for legacy callers.
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


def _resolve_transport_security() -> Any:
    """Server-side transport security settings.

    This project is typically deployed behind a trusted reverse proxy (e.g.,
    Render) and uses explicit authentication/authorization on the tool layer.

    Per operator request, we disable FastMCP transport security enforcement
    (allowed hosts/origins, DNS rebinding protection) so it cannot block
    long-running workflows or internal tooling.
    """

    # NOTE: This does not and cannot disable any platform-level safety systems.
    return None


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
