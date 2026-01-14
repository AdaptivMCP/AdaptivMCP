"""Configuration and logging helpers for the GitHub MCP server."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from typing import Any, Mapping

from github_mcp.mcp_server.schemas import _jsonable


_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def shorten_token(value: object, *, head: int = 8, tail: int = 4) -> object:
    """Shorten opaque identifiers for human-facing logs.

    Render logs are read by humans. Long opaque identifiers (UUIDs, hashes,
    idempotency keys) degrade readability. This helper preserves the original
    value type where possible and shortens only strings that look like tokens.
    """

    if not isinstance(value, str):
        return value

    raw = value.strip()
    if not raw:
        return value

    # If it looks like a UUID, keep the prefix.
    if _UUID_RE.match(raw):
        return raw.split("-")[0]

    # Long hex strings (hashes, digests).
    if len(raw) >= 32 and all(ch in "0123456789abcdefABCDEF" for ch in raw):
        if len(raw) <= head + tail + 1:
            return raw
        return f"{raw[:head]}…{raw[-tail:]}"

    # Base64-ish / URL-safe random strings.
    if len(raw) >= 40 and all(
        ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ("0" <= ch <= "9") or ch in "-_=+/"
        for ch in raw
    ):
        if len(raw) <= head + tail + 1:
            return raw
        return f"{raw[:head]}…{raw[-tail:]}"

    return value


_HUMANIZE_ID_KEYS = {
    "call_id",
    "request_id",
    "session_id",
    "message_id",
    "schema_hash",
    "dedupe_key",
    "idempotency_key",
    "routing_hint",
}


def _sanitize_for_logs(value: object, *, depth: int = 0, max_depth: int = 3) -> object:
    """Recursively sanitize extra payloads for readability in hosted logs."""

    if depth > max_depth:
        return "…"

    if isinstance(value, dict):
        out: dict[str, object] = {}
        for k, v in value.items():
            key = str(k)
            if HUMAN_LOGS and key in _HUMANIZE_ID_KEYS:
                out[key] = shorten_token(v)
            else:
                out[key] = _sanitize_for_logs(v, depth=depth + 1, max_depth=max_depth)
        return out

    if isinstance(value, (list, tuple)):
        items = list(value)
        cap = 20 if HUMAN_LOGS else 100
        trimmed = items[:cap]
        out = [_sanitize_for_logs(v, depth=depth + 1, max_depth=max_depth) for v in trimmed]
        if len(items) > cap:
            out.append(f"…(+{len(items) - cap} more)")
        return out

    if isinstance(value, str):
        # Prefer shortening opaque tokens; keep human strings as-is.
        shortened = shorten_token(value)
        if shortened is not value:
            return shortened
        if HUMAN_LOGS and len(value) > 400:
            return value[:380] + "…"
        return value

    return _jsonable(value)


def summarize_request_context(req: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a compact request context suitable for provider logs.

    The raw request context may include verbose ChatGPT metadata fields (long
    opaque IDs). For hosted logs (Render) we keep only correlation fields that
    are actually useful to operators.
    """

    if not isinstance(req, Mapping):
        return {}

    out: dict[str, Any] = {
        "request_id": shorten_token(req.get("request_id")),
        "path": req.get("path"),
        "session_id": shorten_token(req.get("session_id")),
        "message_id": shorten_token(req.get("message_id")),
    }

    chatgpt = req.get("chatgpt")
    if isinstance(chatgpt, Mapping):
        # Keep only the two most useful identifiers for debugging.
        out["chatgpt"] = {
            "conversation_id": shorten_token(chatgpt.get("conversation_id")),
            "assistant_id": shorten_token(chatgpt.get("assistant_id")),
        }

    # Drop nulls to keep the payload small.
    return {k: v for k, v in out.items() if v not in (None, "")}


def _is_render_runtime() -> bool:
    """Best-effort detection for Render deployments.

    Render sets a number of standard environment variables for running services.
    We use these to adjust provider-facing defaults (e.g., avoid duplicating
    access logs that Render already emits).
    """

    return any(
        os.environ.get(name)
        for name in (
            "RENDER",
            "RENDER_SERVICE_ID",
            "RENDER_SERVICE_NAME",
            "RENDER_EXTERNAL_URL",
            "RENDER_INSTANCE_ID",
            "RENDER_GIT_COMMIT",
        )
    )


def _env_flag(name: str, default: str) -> bool:
    raw = os.environ.get(name, default)
    return str(raw).strip().lower() in ("1", "true", "t", "yes", "y", "on")


def _resolve_log_level(level_name: str | None) -> int:
    if not level_name:
        return logging.INFO

    name = str(level_name).strip().upper()
    if not name:
        return logging.INFO

    # Numeric levels are allowed.
    if name.lstrip("-").isdigit():
        try:
            return int(name)
        except Exception:
            return logging.INFO

    return getattr(logging, name, logging.INFO)


# Configuration and globals
# ------------------------------------------------------------------------------

GITHUB_TOKEN_ENV_VARS = ("GITHUB_PAT", "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_OAUTH_TOKEN")
GITHUB_PAT = os.environ.get("GITHUB_PAT")
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_API_BASE_URL = GITHUB_API_BASE

SANDBOX_CONTENT_BASE_URL = os.environ.get("SANDBOX_CONTENT_BASE_URL")


# Base directory for persistent repo mirrors used by terminal_command and related tools.
# This keeps cloned repositories stable across tool invocations so installations
# and edits survive until explicitly reset or deleted.
def _default_workspace_base_dir() -> str:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if cache_home:
        base_dir = cache_home
    else:
        home_dir = os.path.expanduser("~")
        if home_dir and home_dir != "~":
            base_dir = os.path.join(home_dir, ".cache")
        else:
            base_dir = tempfile.gettempdir()
    return os.path.join(base_dir, "mcp-github-workspaces")


WORKSPACE_BASE_DIR = os.environ.get(
    "MCP_WORKSPACE_BASE_DIR",
    _default_workspace_base_dir(),
)

HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", 150))
GITHUB_REQUEST_TIMEOUT_SECONDS = HTTPX_TIMEOUT
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", 300))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", 200))

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", 80))
FETCH_FILES_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", "80"))
# File cache eviction caps. Set to 0 (or negative) to disable eviction.
FILE_CACHE_MAX_ENTRIES = int(os.environ.get("FILE_CACHE_MAX_ENTRIES", "0"))
FILE_CACHE_MAX_BYTES = int(os.environ.get("FILE_CACHE_MAX_BYTES", "0"))
GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS = int(
    os.environ.get("GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS", "2")
)
GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS = int(
    os.environ.get("GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS", "30")
)
GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS = float(
    os.environ.get("GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS", "1")
)
GITHUB_SEARCH_MIN_INTERVAL_SECONDS = float(
    os.environ.get("GITHUB_SEARCH_MIN_INTERVAL_SECONDS", "2")
)

# Logging controls
# ------------------------------------------------------------------------------
# These settings only affect provider logs (Render / stdout). They do not change
# tool outputs returned to the client.

# Provider log verbosity.
#
# Historically this defaulted to "true" to keep hosted provider logs quiet.
# In practice, hosted environments (Render) already expose request-level logs,
# and operators typically need application/tool-level traces for debugging.
#
# Default to verbose (QUIET_LOGS=false) so Render application logs include
# startup diagnostics, tool traces, and structured errors. Set QUIET_LOGS=true
# explicitly if you want a near-silent log stream.
QUIET_LOGS = _env_flag("QUIET_LOGS", "false")


# Emit richer tool call logs (args/result metadata) suitable for humans reading Render logs.
HUMAN_LOGS = _env_flag("HUMAN_LOGS", "true")

# Log tool call start/completion lines to provider logs.
# When disabled, only warnings/errors (tool_call_failed) are emitted.
#
# Default to enabled so operators can correlate behavior in Render logs without
# turning on additional flags.
LOG_TOOL_CALLS = _env_flag("LOG_TOOL_CALLS", "true")

# Whether to emit tool_call_started lines.
#
# To keep provider logs concise, we default to logging only tool completion
# (success/failure) which already includes correlation ids + duration.
LOG_TOOL_CALL_STARTS = _env_flag("LOG_TOOL_CALL_STARTS", "false")

# When enabled, include full tool args and full tool results in logs.
# WARNING: This can create very large log lines and may stress hosted log ingestion.
LOG_TOOL_PAYLOADS = _env_flag("LOG_TOOL_PAYLOADS", "false")

# When enabled, include outbound GitHub HTTP request/response details in logs.
LOG_GITHUB_HTTP = _env_flag("LOG_GITHUB_HTTP", "false")

# When enabled, include response bodies for GitHub HTTP logs.
# WARNING: This can be very large for search/list endpoints.
LOG_GITHUB_HTTP_BODIES = _env_flag("LOG_GITHUB_HTTP_BODIES", "false")

# Log inbound HTTP requests handled by the ASGI app (provider logs).
# Default to enabled so hosted logs capture request latency/correlation IDs.
# Render already emits request access logs at the platform layer.
# Default to disabling the app-layer access logs on Render to avoid duplicates.
_log_http_default = (
    "false" if _is_render_runtime() and os.environ.get("LOG_HTTP_REQUESTS") is None else "true"
)
LOG_HTTP_REQUESTS = _env_flag("LOG_HTTP_REQUESTS", _log_http_default)

# When enabled, include HTTP request bodies for POST /messages in logs.
# WARNING: Can be large. This does not modify tool outputs.
LOG_HTTP_BODIES = _env_flag("LOG_HTTP_BODIES", "false")

# When enabled, include outbound Render HTTP request/response details in logs.
LOG_RENDER_HTTP = _env_flag("LOG_RENDER_HTTP", "false")

# When enabled, include response bodies for Render HTTP logs.
# WARNING: This can be very large for log endpoints.
LOG_RENDER_HTTP_BODIES = _env_flag("LOG_RENDER_HTTP_BODIES", "false")

# Append structured extras ("data={...}") to provider log lines.
#
# When HUMAN_LOGS is enabled, our primary audience is humans tailing Render logs.
# Extra JSON payloads can become noisy and redundant (especially alongside
# platform-level access logs). Default to:
# - INFO: no appended JSON
# - WARNING/ERROR: appended JSON for debugging
#
# Set LOG_APPEND_EXTRAS_JSON=true to force extras on INFO as well.
LOG_APPEND_EXTRAS_JSON = _env_flag(
    "LOG_APPEND_EXTRAS_JSON",
    "false" if HUMAN_LOGS else "true",
)

# Repo mirror diff application can be slow for large diffs. Keep this configurable.
WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS = int(
    os.environ.get("MCP_WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS", "300")
)

GITHUB_MCP_GIT_IDENTITY_ENV_VARS = (
    "GITHUB_MCP_GIT_AUTHOR_NAME",
    "GITHUB_MCP_GIT_AUTHOR_EMAIL",
    "GITHUB_MCP_GIT_COMMITTER_NAME",
    "GITHUB_MCP_GIT_COMMITTER_EMAIL",
)

DEFAULT_GIT_IDENTITY = {
    "author_name": "Adaptiv MCP",
    "author_email": "adaptiv-mcp@local",
    "committer_name": "Adaptiv MCP",
    "committer_email": "adaptiv-mcp@local",
}

# Back-compat placeholder values from earlier versions.
PLACEHOLDER_GIT_IDENTITY = {
    "author_name": "Ally",
    "author_email": "ally@example.com",
    "committer_name": "Ally",
    "committer_email": "ally@example.com",
}


def _slugify_app_name(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().lower()
    parts: list[str] = []
    prev_dash = False
    for ch in raw:
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            parts.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                parts.append("-")
                prev_dash = True
    slug = "".join(parts).strip("-")
    return slug or None


def _resolve_app_identity() -> dict[str, str] | None:
    app_name = os.environ.get("GITHUB_APP_NAME")
    app_slug = os.environ.get("GITHUB_APP_SLUG") or _slugify_app_name(app_name)
    app_id = os.environ.get("GITHUB_APP_ID") or os.environ.get("GITHUB_APP_INSTALLATION_ID")

    bot_login = None
    if app_slug:
        bot_login = f"{app_slug}[bot]"
    elif app_id:
        bot_login = f"github-app-{app_id}[bot]"

    if not (app_name or bot_login or app_id):
        return None

    name = app_name or bot_login or "GitHub App"
    email = None
    if bot_login:
        email = f"{bot_login}@users.noreply.github.com"
    elif app_id:
        email = f"app+{app_id}@users.noreply.github.com"

    if not email:
        return None

    return {"name": name, "email": email}


def _resolve_git_identity() -> dict[str, object]:
    app_identity = _resolve_app_identity() or {}

    def resolve_value(
        *,
        explicit_env: str | None,
        app_value: str | None,
        default_value: str,
    ) -> tuple[str, str]:
        if explicit_env:
            return explicit_env, "explicit_env"
        if app_value:
            return app_value, "app_metadata"
        return default_value, "default_placeholder"

    author_name, author_name_source = resolve_value(
        explicit_env=os.environ.get("GITHUB_MCP_GIT_AUTHOR_NAME"),
        app_value=app_identity.get("name"),
        default_value=DEFAULT_GIT_IDENTITY["author_name"],
    )
    author_email, author_email_source = resolve_value(
        explicit_env=os.environ.get("GITHUB_MCP_GIT_AUTHOR_EMAIL"),
        app_value=app_identity.get("email"),
        default_value=DEFAULT_GIT_IDENTITY["author_email"],
    )

    committer_name_env = os.environ.get("GITHUB_MCP_GIT_COMMITTER_NAME")
    committer_name = None
    committer_name_source = None
    if committer_name_env:
        committer_name = committer_name_env
        committer_name_source = "explicit_env"
    elif app_identity.get("name"):
        committer_name = app_identity.get("name")
        committer_name_source = "app_metadata"
    else:
        committer_name = author_name
        committer_name_source = "author_fallback"

    committer_email_env = os.environ.get("GITHUB_MCP_GIT_COMMITTER_EMAIL")
    committer_email = None
    committer_email_source = None
    if committer_email_env:
        committer_email = committer_email_env
        committer_email_source = "explicit_env"
    elif app_identity.get("email"):
        committer_email = app_identity.get("email")
        committer_email_source = "app_metadata"
    else:
        committer_email = author_email
        committer_email_source = "author_fallback"

    sources = {
        "author_name": author_name_source,
        "author_email": author_email_source,
        "committer_name": committer_name_source,
        "committer_email": committer_email_source,
    }

    # Mark placeholder active only when the fallback values are clearly placeholders.
    # Using DEFAULT_GIT_IDENTITY as the fallback identity is valid for deployments that do
    # not set explicit git identity env vars.
    placeholder_active = False
    for key, source in sources.items():
        if source != "default_placeholder":
            continue
        value = {
            "author_name": author_name,
            "author_email": author_email,
            "committer_name": committer_name,
            "committer_email": committer_email,
        }[key]
        if value == PLACEHOLDER_GIT_IDENTITY[key]:
            placeholder_active = True
            break

    return {
        "author_name": author_name,
        "author_email": author_email,
        "committer_name": committer_name,
        "committer_email": committer_email,
        "sources": sources,
        "placeholder_active": placeholder_active,
    }


_GIT_IDENTITY = _resolve_git_identity()

GIT_AUTHOR_NAME = _GIT_IDENTITY["author_name"]
GIT_AUTHOR_EMAIL = _GIT_IDENTITY["author_email"]
GIT_COMMITTER_NAME = _GIT_IDENTITY["committer_name"]
GIT_COMMITTER_EMAIL = _GIT_IDENTITY["committer_email"]
GIT_IDENTITY_SOURCES = _GIT_IDENTITY["sources"]
GIT_IDENTITY_PLACEHOLDER_ACTIVE = bool(_GIT_IDENTITY["placeholder_active"])


def git_identity_warnings() -> list[str]:
    if not GIT_IDENTITY_PLACEHOLDER_ACTIVE:
        return []
    return [
        "Git identity is using placeholder values. Configure GITHUB_MCP_GIT_AUTHOR_NAME, "
        "GITHUB_MCP_GIT_AUTHOR_EMAIL, GITHUB_MCP_GIT_COMMITTER_NAME, and "
        "GITHUB_MCP_GIT_COMMITTER_EMAIL (or set GitHub App metadata) to ensure commits "
        "are attributed correctly."
    ]


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
# Default to a compact, scannable format.
LOG_FORMAT = os.environ.get(
    "LOG_FORMAT",
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


class _StructuredFormatter(logging.Formatter):
    """Formatter that appends structured extra fields as JSON."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting
        base = super().format(record)
        extra_payload = _extract_log_extras(record)
        if extra_payload:
            # Keep INFO lines scan-friendly for humans.
            # Always include extras for WARNING/ERROR (or when explicitly enabled).
            if LOG_APPEND_EXTRAS_JSON or record.levelno >= logging.WARNING:
                extra_payload = _sanitize_for_logs(extra_payload)
                extra_json = json.dumps(
                    extra_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                return f"{base} | data={extra_json}"
        return base


_STANDARD_LOG_FIELDS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


def _extract_log_extras(record: logging.LogRecord) -> dict[str, object]:
    extras: dict[str, object] = {}

    # NOTE:
    # The formatter mutates the record by injecting fields like `asctime` and
    # computing `message` from msg/args. When we later append `data=<json>`
    # using record.__dict__, those injected fields can be picked up as extras and
    # cause double-encoding (lots of backslashes) and extremely noisy logs.
    _exclude_dynamic = {"asctime", "message"}

    for key, value in record.__dict__.items():
        if key in _STANDARD_LOG_FIELDS or key.startswith("_"):
            continue
        if key in _exclude_dynamic:
            continue
        extras[key] = _jsonable(value)

    return extras


def _configure_logging() -> None:
    # Avoid reconfiguring during module reloads.
    root = logging.getLogger()
    if getattr(root, "_github_mcp_configured", False):
        return

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(_StructuredFormatter(LOG_FORMAT))
    console_handler.setLevel(logging.CRITICAL if QUIET_LOGS else _resolve_log_level(LOG_LEVEL))

    logging.basicConfig(
        level=logging.CRITICAL if QUIET_LOGS else _resolve_log_level(LOG_LEVEL),
        handlers=[console_handler],
        force=True,
    )

    # Reduce noisy framework logs in provider log streams.
    for noisy in (
        "uvicorn.access",
        "mcp",
        "mcp.server",
        "mcp.server.lowlevel.server",
        "httpx",
        "httpcore",
    ):
        logging.getLogger(noisy).setLevel(logging.ERROR if QUIET_LOGS else logging.WARNING)

    setattr(root, "_github_mcp_configured", True)


_configure_logging()

BASE_LOGGER = logging.getLogger("github_mcp")
# Back-compat: a single provider logger is sufficient.
ERRORS_LOGGER = BASE_LOGGER
GITHUB_LOGGER = logging.getLogger("github_mcp.github_client")

SERVER_START_TIME = time.time()

# Best-effort commit identifier for runtime diagnostics.
SERVER_GIT_COMMIT = (
    os.environ.get("RENDER_GIT_COMMIT")
    or os.environ.get("GITHUB_SHA")
    or os.environ.get("GIT_COMMIT")
    or os.environ.get("SOURCE_VERSION")
)

# ------------------------------------------------------------------------------
# Render API configuration
# ------------------------------------------------------------------------------

RENDER_API_BASE = os.environ.get("RENDER_API_BASE", "https://api.render.com")
RENDER_TOKEN_ENV_VARS = (
    "RENDER_API_KEY",
    "RENDER_API_TOKEN",
    "RENDER_TOKEN",
)

RENDER_RATE_LIMIT_RETRY_MAX_ATTEMPTS = int(
    os.environ.get("RENDER_RATE_LIMIT_RETRY_MAX_ATTEMPTS", "2")
)
RENDER_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS = int(
    os.environ.get("RENDER_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS", "30")
)
RENDER_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS = float(
    os.environ.get("RENDER_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS", "1")
)

__all__ = [
    "BASE_LOGGER",
    "ERRORS_LOGGER",
    "FETCH_FILES_CONCURRENCY",
    "FILE_CACHE_MAX_BYTES",
    "FILE_CACHE_MAX_ENTRIES",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_IDENTITY_PLACEHOLDER_ACTIVE",
    "GIT_IDENTITY_SOURCES",
    "GITHUB_API_BASE",
    "GITHUB_MCP_GIT_IDENTITY_ENV_VARS",
    "GITHUB_TOKEN_ENV_VARS",
    "GITHUB_LOGGER",
    "GITHUB_PAT",
    "HTTPX_MAX_CONNECTIONS",
    "HTTPX_MAX_KEEPALIVE",
    "HTTPX_TIMEOUT",
    "LOG_RENDER_HTTP",
    "LOG_RENDER_HTTP_BODIES",
    "LOG_TOOL_CALLS",
    "LOG_TOOL_CALL_STARTS",
    "LOG_HTTP_REQUESTS",
    "MAX_CONCURRENCY",
    "RENDER_API_BASE",
    "RENDER_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS",
    "RENDER_RATE_LIMIT_RETRY_MAX_ATTEMPTS",
    "RENDER_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS",
    "RENDER_TOKEN_ENV_VARS",
    "SERVER_GIT_COMMIT",
    "SERVER_START_TIME",
    "WORKSPACE_BASE_DIR",
    "SANDBOX_CONTENT_BASE_URL",
    "git_identity_warnings",
    "shorten_token",
    "summarize_request_context",
]
