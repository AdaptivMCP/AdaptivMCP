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

REQUEST_MESSAGE_ID: ContextVar[str | None] = ContextVar(
    "REQUEST_MESSAGE_ID", default=None
)
REQUEST_SESSION_ID: ContextVar[str | None] = ContextVar(
    "REQUEST_SESSION_ID", default=None
)
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

# When auto-approve is disabled, some clients perform an explicit approval step.
# This flag allows per-request overrides without mutating global environment state.
REQUEST_WRITE_APPROVED: ContextVar[bool | None] = ContextVar(
    "REQUEST_WRITE_APPROVED", default=None
)

# End-to-end correlation identifier for each HTTP request.
# Derived from the incoming X-Request-Id header when present; otherwise generated server-side.
REQUEST_ID: ContextVar[str | None] = ContextVar("REQUEST_ID", default=None)

# These are imported by main.py in your repo; keep names stable.
REQUEST_PATH: ContextVar[str | None] = ContextVar("REQUEST_PATH", default=None)
REQUEST_RECEIVED_AT: ContextVar[float | None] = ContextVar(
    "REQUEST_RECEIVED_AT", default=None
)


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
    "REQUEST_WRITE_APPROVED",
    "get_request_context",
    "get_request_id",
    "get_auto_approve_enabled",
    "peek_auto_approve_enabled",
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
    """Extract safe request metadata headers for logging and request context."""

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


AUTO_APPROVE_ENV_VARS = (
    "ADAPTIV_MCP_AUTO_APPROVE",
    "MCP_AUTO_APPROVE",
    "AUTO_APPROVE",
)
AUTO_APPROVE_DEFAULT = True


def _auto_approve_from_env() -> tuple[bool, str]:
    for name in AUTO_APPROVE_ENV_VARS:
        if name in os.environ:
            return _parse_bool(os.environ.get(name)), name
    return AUTO_APPROVE_DEFAULT, "default"


class _WriteAllowedFlag:
    """
    Drop-in compatible:
    - bool(WRITE_ALLOWED)
    - WRITE_ALLOWED.value
    - WRITE_ALLOWED.value = True/False

    Compatibility shim: write approval follows the auto-approve environment gate.
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
_LAST_AUTO_APPROVE_VALUE: bool | None = None


def _update_write_gate_cache(value: bool) -> None:
    global _LAST_AUTO_APPROVE_VALUE

    previous = _LAST_AUTO_APPROVE_VALUE
    _LAST_AUTO_APPROVE_VALUE = value
    WRITE_ALLOWED._cache_value = value

    if previous is None:
        from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS

        if not _REGISTERED_MCP_TOOLS:
            return

    if previous == value:
        return

    from github_mcp.mcp_server.decorators import refresh_registered_tool_metadata

    refresh_registered_tool_metadata(_write_allowed=value)


def get_write_allowed(*, refresh_after_seconds: float = 0.5) -> bool:
    """
    Compatibility shim returning the auto-approve gate value.

    refresh_after_seconds is ignored but kept for backwards compatibility.
    """
    del refresh_after_seconds
    env_value, _source = _auto_approve_from_env()
    # Keep global caches in sync with environment (used for tool metadata refresh).
    _update_write_gate_cache(env_value)

    # If the environment enables auto-approve, it is authoritative. Request-scoped
    # overrides are only meaningful when auto-approve is disabled.
    if env_value:
        return True

    # Request-scoped override: used when a human explicitly approves a write
    # action in the client while auto-approve is disabled.
    override = REQUEST_WRITE_APPROVED.get()
    if override is not None:
        return bool(override)

    return False


def set_write_allowed(approved: bool) -> bool:
    """
    Compatibility shim for legacy callers.
    """
    # Only meaningful when auto-approve is disabled.
    env_value, _source = _auto_approve_from_env()
    _update_write_gate_cache(env_value)
    if env_value:
        # Preserve historical return type: write is allowed.
        return True

    REQUEST_WRITE_APPROVED.set(bool(approved))
    return bool(approved)


def get_auto_approve_enabled(*, refresh_after_seconds: float = 0.5) -> bool:
    del refresh_after_seconds
    value, _source = _auto_approve_from_env()
    _update_write_gate_cache(value)
    return value


def peek_auto_approve_enabled() -> bool:
    """Read the auto-approve flag from the environment without side effects.

    Unlike get_auto_approve_enabled(), this function does *not* update caches or
    trigger tool metadata refresh. It is intended for response-shaping logic
    (e.g., UI hints) where we want a fast, non-recursive read of the current
    setting.
    """

    value, _source = _auto_approve_from_env()
    return bool(value)


def get_write_allowed_debug() -> dict[str, Any]:
    value, source = _auto_approve_from_env()
    return {
        "value": value,
        "cache": {
            "value": WRITE_ALLOWED._cache_value,
            "source": source,
        },
    }


COMPACT_METADATA_DEFAULT = _parse_bool(
    os.environ.get("ADAPTIV_MCP_COMPACT_METADATA_DEFAULT", "true")
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
    if TransportSecuritySettings is None:
        return None
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


# ------------------------------------------------------------------------------
# Server identity (exposed to clients)
# ------------------------------------------------------------------------------

SERVER_NAME = os.environ.get("ADAPTIV_MCP_SERVER_NAME", "Adaptiv MCP")

_raw_version = (
    os.environ.get("ADAPTIV_MCP_SERVER_VERSION")
    or os.environ.get("ADAPTIV_MCP_VERSION")
    or os.environ.get("RENDER_GIT_COMMIT")
    or os.environ.get("GITHUB_SHA")
    or os.environ.get("COMMIT_SHA")
    or "dev"
)
SERVER_VERSION = _raw_version.strip() if isinstance(_raw_version, str) else "dev"
if re.fullmatch(r"[0-9a-fA-F]{7,40}", SERVER_VERSION):
    SERVER_VERSION = f"git-{SERVER_VERSION[:12].lower()}"


def _apply_server_identity(server_obj: object | None) -> None:
    if server_obj is None:
        return
    try:
        setattr(server_obj, "name", SERVER_NAME)
        setattr(server_obj, "version", SERVER_VERSION)
    except Exception:
        return


try:
    from mcp.server.fastmcp import FastMCP  # type: ignore

    FASTMCP_AVAILABLE = True

    mcp = FastMCP(
        SERVER_NAME,
        host=os.environ.get("FASTMCP_HOST", "0.0.0.0"),  # nosec B104
        transport_security=_resolve_transport_security(),
    )

    _apply_server_identity(getattr(mcp, "_mcp_server", None))
except Exception as exc:  # pragma: no cover - used when dependency missing
    FASTMCP_AVAILABLE = False
    missing_exc = exc

    class _MissingFastMCP:
        def tool(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("FastMCP import failed") from missing_exc

        def __getattr__(self, name: str) -> Any:
            raise AttributeError(name)

    mcp = _MissingFastMCP()
