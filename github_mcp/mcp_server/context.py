# github_mcp/mcp_server/context.py
from __future__ import annotations

import json
import logging
import os
import time
from collections import Counter, deque
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from github_mcp.mcp_server.schemas import _jsonable

# ------------------------------------------------------------------------------
# Request-scoped context (used for correlation/logging/dedupe)
# ------------------------------------------------------------------------------

REQUEST_MESSAGE_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_MESSAGE_ID", default=None)
REQUEST_SESSION_ID: ContextVar[Optional[str]] = ContextVar("REQUEST_SESSION_ID", default=None)

# These are imported by main.py in your repo; keep names stable.
REQUEST_PATH: ContextVar[Optional[str]] = ContextVar("REQUEST_PATH", default=None)
REQUEST_RECEIVED_AT: ContextVar[Optional[float]] = ContextVar("REQUEST_RECEIVED_AT", default=None)

_LOGGER = logging.getLogger(__name__)

def get_request_context() -> dict[str, Any]:
    return {
        "path": REQUEST_PATH.get(),
        "received_at": REQUEST_RECEIVED_AT.get(),
        "session_id": REQUEST_SESSION_ID.get(),
        "message_id": REQUEST_MESSAGE_ID.get(),
    }

# ------------------------------------------------------------------------------
# Dynamic write gate (cross-worker)
# ------------------------------------------------------------------------------

WRITE_ALLOWED_FILE = Path(os.environ.get("GITHUB_MCP_WRITE_ALLOWED_FILE", "/tmp/github_mcp_write_allowed.json"))


def _parse_bool(value: Optional[str]) -> bool:
    v = (value or "").strip().lower()
    return v in ("1", "true", "t", "yes", "y", "on")


def _env_default_write_allowed() -> bool:
    # Matches your expectation: default true unless explicitly false
    return _parse_bool(os.environ.get("GITHUB_MCP_WRITE_ALLOWED", "true"))


@dataclass
class _WriteAllowedCache:
    value: bool
    ts: float
    source: str


class _WriteAllowedFlag:
    """
    Drop-in compatible:
      - bool(WRITE_ALLOWED)
      - WRITE_ALLOWED.value
      - WRITE_ALLOWED.value = True/False

    Backed by a JSON file in /tmp so multiple workers/processes stay in sync.
    """

    def __init__(self) -> None:
        self._cache = _WriteAllowedCache(value=_env_default_write_allowed(), ts=0.0, source="env")

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
    Returns effective write gate. Reads the /tmp file periodically (cached),
    so write gate changes apply across workers.
    """
    now = time.time()
    if (now - WRITE_ALLOWED._cache.ts) < refresh_after_seconds:
        return WRITE_ALLOWED._cache.value

    # Prefer file (dynamic)
    try:
        if WRITE_ALLOWED_FILE.exists():
            data = json.loads(WRITE_ALLOWED_FILE.read_text(encoding="utf-8"))
            val = bool(data.get("value", False))
            WRITE_ALLOWED._cache = _WriteAllowedCache(value=val, ts=now, source="file")
            return val
    except Exception:
        # Fall back to env/cache on read/parse issues
        _LOGGER.warning(
            "Failed to read write-allowed file; falling back to env default.",
            exc_info=True,
        )
        pass

    # Fallback to env
    val = _env_default_write_allowed()
    WRITE_ALLOWED._cache = _WriteAllowedCache(value=val, ts=now, source="env")
    return val


def set_write_allowed(approved: bool) -> bool:
    """
    Persists write gate to /tmp so all workers see it.
    """
    now = time.time()
    WRITE_ALLOWED_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload = {"value": bool(approved), "updated_at": now}
    tmp_path = WRITE_ALLOWED_FILE.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(WRITE_ALLOWED_FILE)

    WRITE_ALLOWED._cache = _WriteAllowedCache(value=bool(approved), ts=now, source="file")
    return WRITE_ALLOWED._cache.value


def get_write_allowed_debug() -> dict[str, Any]:
    return {
        "value": get_write_allowed(refresh_after_seconds=0.0),
        "env_default": _env_default_write_allowed(),
        "file_path": str(WRITE_ALLOWED_FILE),
        "cache": {
            "value": WRITE_ALLOWED._cache.value,
            "source": WRITE_ALLOWED._cache.source,
            "updated_at": WRITE_ALLOWED._cache.ts,
        },
    }


# ------------------------------------------------------------------------------
# Recent tool events (non-blocking telemetry)
# ------------------------------------------------------------------------------

_DIAGNOSTICS_ENABLED = _parse_bool(os.environ.get("GITHUB_MCP_DIAGNOSTICS", "true"))
_RECORD_RECENT_EVENTS = _parse_bool(os.environ.get("GITHUB_MCP_RECORD_RECENT_EVENTS", "true"))

# Keep bounded; default is conservative.
_MAX_RECENT_EVENTS = int(os.environ.get("GITHUB_MCP_MAX_RECENT_EVENTS", "200"))

_recent_tool_events: deque[dict[str, Any]] = deque(maxlen=_MAX_RECENT_EVENTS)
_recent_tool_event_counters: Counter[str] = Counter()
_recent_tool_events_dropped: int = 0
_recent_tool_events_total: int = 0

# Compatibility exports for older call sites.
RECENT_TOOL_EVENTS = _recent_tool_events
RECENT_TOOL_EVENTS_CAPACITY = _MAX_RECENT_EVENTS
RECENT_TOOL_EVENTS_DROPPED = _recent_tool_events_dropped
RECENT_TOOL_EVENTS_TOTAL = _recent_tool_events_total

COMPACT_METADATA_DEFAULT = _parse_bool(os.environ.get("GITHUB_MCP_COMPACT_METADATA_DEFAULT", "true"))
_TOOL_EXAMPLES: dict[str, Any] = {}


def diagnostics_enabled() -> bool:
    return _DIAGNOSTICS_ENABLED


def record_recent_events_enabled() -> bool:
    return _RECORD_RECENT_EVENTS


def record_tool_event(event: dict[str, Any]) -> None:
    """
    Best-effort, non-blocking telemetry.
    """
    global _recent_tool_events_dropped, _recent_tool_events_total, RECENT_TOOL_EVENTS_DROPPED, RECENT_TOOL_EVENTS_TOTAL

    if not (_DIAGNOSTICS_ENABLED and _RECORD_RECENT_EVENTS):
        return

    try:
        safe_event = _jsonable(event)
        before_len = len(_recent_tool_events)
        _recent_tool_events.append(safe_event)
        after_len = len(_recent_tool_events)

        # If we were at maxlen, append will evict one; treat as dropped for accounting.
        if after_len == before_len and after_len == _MAX_RECENT_EVENTS:
            _recent_tool_events_dropped += 1
            RECENT_TOOL_EVENTS_DROPPED = _recent_tool_events_dropped

        tool_name = str(safe_event.get("tool", safe_event.get("tool_name", "unknown")))
        _recent_tool_event_counters[tool_name] += 1
        _recent_tool_events_total += 1
        RECENT_TOOL_EVENTS_TOTAL = _recent_tool_events_total
    except Exception:
        # Telemetry must never break execution.
        _LOGGER.exception("Failed to record recent tool event.")
        return


def _record_recent_tool_event(event: dict[str, Any]) -> None:
    record_tool_event(event)


try:
    from mcp.server.fastmcp import FastMCP  # type: ignore
    from mcp.server.transport_security import TransportSecuritySettings  # type: ignore

    FASTMCP_AVAILABLE = True

    def _extract_hostname(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if "://" in cleaned:
            parsed = urlparse(cleaned)
            host = parsed.hostname or parsed.netloc
            return host or None
        return cleaned


    def _render_external_hosts() -> list[str]:
        hostnames: list[str] = []
        for env_name in ("RENDER_EXTERNAL_HOSTNAME", "RENDER_EXTERNAL_URL"):
            hostname = _extract_hostname(os.getenv(env_name))
            if hostname:
                hostnames.append(hostname)
        return hostnames


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
        allowed_hosts = [host.strip() for host in (allowed_hosts_env or "").split(",") if host.strip()]
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


def get_recent_tool_events(*, limit: int = 50) -> dict[str, Any]:
    """
    Returns the newest events first.
    """
    if limit <= 0:
        limit = 1
    if limit > _MAX_RECENT_EVENTS:
        limit = _MAX_RECENT_EVENTS

    events = list(_recent_tool_events)[-limit:]
    events.reverse()

    return {
        "enabled": bool(_DIAGNOSTICS_ENABLED and _RECORD_RECENT_EVENTS),
        "maxlen": _MAX_RECENT_EVENTS,
        "dropped": _recent_tool_events_dropped,
        "counts": dict(_recent_tool_event_counters),
        "events": events,
    }
