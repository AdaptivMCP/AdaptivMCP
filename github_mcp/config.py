"""Configuration and logging helpers for the GitHub MCP server."""

from __future__ import annotations

import importlib.util
import logging
import os
import re
import tempfile
import time
from collections.abc import Mapping
from typing import Any

from github_mcp.mcp_server.schemas import _jsonable

if importlib.util.find_spec("dotenv"):
    from dotenv import load_dotenv

    load_dotenv()

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Supported runtime versions for the server.
MIN_PYTHON_VERSION = (3, 12)
MAX_PYTHON_VERSION = (3, 13)


def shorten_token(value: object, *, head: int = 8, tail: int = 4) -> object:
    """Optionally shorten identifiers for scan-friendly provider logs.

    By default, self-hosted deployments preserve full-fidelity values.
    Hosted providers (e.g., Render) tend to benefit from shorter correlation
    IDs to keep log lines readable.

    Control via:
      - ADAPTIV_MCP_SHORTEN_TOKENS=1|0
    """

    raw = os.environ.get("ADAPTIV_MCP_SHORTEN_TOKENS")
    if raw is None:
        # Default to shortening on Render only.
        shorten = _is_render_runtime()
    else:
        shorten = str(raw).strip().lower() in ("1", "true", "t", "yes", "y", "on")

    if not shorten:
        return value

    if value is None:
        return value
    s = str(value).strip()
    if not s:
        return value
    if len(s) <= head + tail + 2:
        return s
    if _UUID_RE.match(s):
        return s.split("-")[0]
    return f"{s[:head]}…{s[-tail:]}"


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
    """Sanitize payloads for provider logs.

    Hosted log UIs can become unusably noisy if we emit full-fidelity nested
    payloads (large request contexts, HTTP bodies, tool results). By default we:
      - cap string lengths,
      - cap list lengths,
      - cap nesting depth.

    Self-hosted deployments can opt into full fidelity via:
      - ADAPTIV_MCP_LOG_FULL_FIDELITY=1
    """

    full_raw = os.environ.get("ADAPTIV_MCP_LOG_FULL_FIDELITY")
    if full_raw is None:
        full_fidelity = not _is_render_runtime()
    else:
        full_fidelity = str(full_raw).strip().lower() in ("1", "true", "t", "yes", "y", "on")

    if full_fidelity:
        return _jsonable(value)

    max_depth_cfg = int(os.environ.get("ADAPTIV_MCP_LOG_MAX_DEPTH", "4") or "4")
    max_list_cfg = int(os.environ.get("ADAPTIV_MCP_LOG_MAX_LIST", "50") or "50")
    max_str_cfg = int(os.environ.get("ADAPTIV_MCP_LOG_MAX_STR", "500") or "500")

    def _clip_str(s: str) -> str:
        s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        s = " ".join(s.split())
        if max_str_cfg > 0 and len(s) > max_str_cfg:
            return s[: max(0, max_str_cfg - 1)] + "…"
        return s

    def walk(v: object, d: int) -> object:
        if v is None or isinstance(v, (bool, int, float)):
            return v
        if isinstance(v, str):
            return _clip_str(v)

        if d >= max(0, max_depth_cfg):
            # Depth cap: keep a short scalar-ish representation.
            try:
                return _clip_str(str(v))
            except Exception:
                return "…"

        if isinstance(v, Mapping):
            out: dict[str, object] = {}
            for k, vv in list(v.items())[:200]:
                out[str(k)] = walk(vv, d + 1)
            if len(v) > 200:
                out["…"] = f"({len(v) - 200} more keys)"
            return out

        if isinstance(v, list):
            items = [walk(x, d + 1) for x in v[: max(0, max_list_cfg)]]
            if max_list_cfg > 0 and len(v) > max_list_cfg:
                items.append(f"… ({len(v) - max_list_cfg} more)")
            return items

        try:
            return _clip_str(str(v))
        except Exception:
            return "…"

    try:
        jsonable = _jsonable(value)
    except Exception:
        jsonable = value
    return walk(jsonable, depth)


def summarize_request_context(req: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return request context for provider logs.

    Defaults:
      - Render: compact snapshot (correlation fields only)
      - Self-hosted: full request context

    Override via:
      - ADAPTIV_MCP_LOG_FULL_REQUEST_CONTEXT=1|0
    """

    if not isinstance(req, Mapping):
        return {}

    full_raw = os.environ.get("ADAPTIV_MCP_LOG_FULL_REQUEST_CONTEXT")
    if full_raw is None:
        full = not _is_render_runtime()
    else:
        full = str(full_raw).strip().lower() in ("1", "true", "t", "yes", "y", "on")

    if not full:
        return snapshot_request_context(req)

    try:
        return _jsonable(dict(req))
    except Exception:
        return {}


def snapshot_request_context(req: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a compact request context snapshot for provider logs.

    Provider log UIs (e.g., Render) are optimized for scanning. Full request
    context includes many null/unset fields; this snapshot keeps only stable
    correlation keys that are typically populated.

    This does not affect tool outputs returned to clients.
    """

    if not isinstance(req, Mapping) or not req:
        return {}

    out: dict[str, Any] = {}
    for key in (
        "request_id",
        "idempotency_key",
        "dedupe_key",
        "path",
        "session_id",
        "message_id",
        "routing_hint",
    ):
        val = req.get(key)
        if val is None or val == "":
            continue
        if key == "path" and isinstance(val, str) and val.startswith("/sse"):
            # Avoid repeating transport-level SSE paths.
            continue
        out[key] = val

    chatgpt = req.get("chatgpt")
    if isinstance(chatgpt, Mapping) and chatgpt:
        # Keep only IDs that help correlate across systems.
        cg_out: dict[str, Any] = {}
        for k in (
            "conversation_id",
            "assistant_id",
            "project_id",
            "organization_id",
            "user_id",
            "session_id",
        ):
            v = chatgpt.get(k)
            if v is None or v == "":
                continue
            cg_out[k] = v
        if cg_out:
            out["chatgpt"] = cg_out

    try:
        return _jsonable(out)
    except Exception:
        return out


def _humanize_id_for_log_line(value: object, *, head: int = 8, tail: int = 4) -> str:
    """Return a compact representation of an identifier for single-line logs."""

    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    if len(raw) <= head + tail + 2:
        return raw
    if _UUID_RE.match(raw):
        # Render request IDs are frequently UUIDs; show the first segment.
        return raw.split("-")[0]
    return f"{raw[:head]}…{raw[-tail:]}"


def format_log_context(req: Mapping[str, Any] | None) -> str:
    """Format request correlation fields for single-line provider logs."""

    snap = snapshot_request_context(req)
    if not snap:
        return ""

    bits: list[str] = []

    def add(key: str, label: str) -> None:
        val = snap.get(key)
        if val is None or val == "":
            return
        bits.append(f"{label}={_humanize_id_for_log_line(val)}")

    add("request_id", "rid")
    add("session_id", "sid")
    add("message_id", "mid")
    add("idempotency_key", "idem")
    add("dedupe_key", "dedupe")
    add("routing_hint", "route")

    chatgpt = snap.get("chatgpt")
    if isinstance(chatgpt, Mapping):
        for key, label in (
            ("conversation_id", "cg_conv"),
            ("assistant_id", "cg_asst"),
            ("project_id", "cg_proj"),
            ("organization_id", "cg_org"),
            ("user_id", "cg_user"),
            ("session_id", "cg_sess"),
        ):
            val = chatgpt.get(key)
            if val is None or val == "":
                continue
            bits.append(f"{label}={_humanize_id_for_log_line(val)}")

    return " ".join(bits)


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

# NOTE: For outbound HTTP (GitHub/Render), timeouts are configurable via env.
# Semantics:
# - Unset/empty -> no client-side timeout
# - "0" (or any <= 0 value) -> no client-side timeout
# - > 0 -> timeout seconds
_raw_httpx_timeout = os.environ.get("HTTPX_TIMEOUT")
if _raw_httpx_timeout is None or not str(_raw_httpx_timeout).strip():
    HTTPX_TIMEOUT = None
else:
    try:
        _v = float(str(_raw_httpx_timeout).strip())
        HTTPX_TIMEOUT = None if _v <= 0 else _v
    except Exception:
        HTTPX_TIMEOUT = None

GITHUB_REQUEST_TIMEOUT_SECONDS = HTTPX_TIMEOUT
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", 300))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", 200))

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", 80))
FETCH_FILES_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", "80"))
# File cache eviction caps. Set to 0 (or negative) to disable eviction.
FILE_CACHE_MAX_ENTRIES = int(os.environ.get("FILE_CACHE_MAX_ENTRIES", "0"))
FILE_CACHE_MAX_BYTES = int(os.environ.get("FILE_CACHE_MAX_BYTES", "0"))

# Workspace / command timeouts.
# Semantics: 0 (or negative) disables timeouts.
ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS = int(
    os.environ.get("ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS", "0")
)
ADAPTIV_MCP_DEP_INSTALL_TIMEOUT_SECONDS = int(
    os.environ.get("ADAPTIV_MCP_DEP_INSTALL_TIMEOUT_SECONDS", "0")
)
ADAPTIV_MCP_PREFLIGHT_TIMEOUT_SECONDS = int(
    os.environ.get("ADAPTIV_MCP_PREFLIGHT_TIMEOUT_SECONDS", "0")
)
ADAPTIV_MCP_TIMEOUT_COLLECT_SECONDS = int(
    os.environ.get("ADAPTIV_MCP_TIMEOUT_COLLECT_SECONDS", "0")
)
ADAPTIV_MCP_DISPATCH_PROBE_COOLDOWN_SECONDS = int(
    os.environ.get("ADAPTIV_MCP_DISPATCH_PROBE_COOLDOWN_SECONDS", "0")
)
ADAPTIV_MCP_WORKFLOW_DISPATCH_POLL_DEADLINE_SECONDS = int(
    os.environ.get("ADAPTIV_MCP_WORKFLOW_DISPATCH_POLL_DEADLINE_SECONDS", "0")
)

_include_b64 = os.environ.get("ADAPTIV_MCP_INCLUDE_BASE64_CONTENT", "0").strip().lower()
ADAPTIV_MCP_INCLUDE_BASE64_CONTENT = _include_b64 in (
    "1",
    "true",
    "t",
    "yes",
    "y",
    "on",
)
GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS = int(
    os.environ.get("GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS", "2")
)
GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS = int(
    os.environ.get("GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS", "30")
)
GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS = float(
    os.environ.get("GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS", "1")
)
# Search throttling (client-side). Set to 0 to disable.
GITHUB_SEARCH_MIN_INTERVAL_SECONDS = float(
    os.environ.get("GITHUB_SEARCH_MIN_INTERVAL_SECONDS", "0")
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
# Whether to emit tool_call_started lines.
#
# In developer-facing environments, the start line is the most actionable
# signal (it answers: what is the server doing right now?). Keep it on by
# default when HUMAN_LOGS are enabled.
_log_tool_call_starts_default = "true" if HUMAN_LOGS else "false"
LOG_TOOL_CALL_STARTS = _env_flag("LOG_TOOL_CALL_STARTS", _log_tool_call_starts_default)

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

# Include compact request correlation fields (request_id + ChatGPT ids) inline
# in single-line provider logs (tool calls, outbound HTTP, etc.).
LOG_INLINE_CONTEXT = _env_flag(
    "ADAPTIV_MCP_LOG_CONTEXT",
    "true" if HUMAN_LOGS else "false",
)

# When enabled, include outbound Render HTTP request/response details in logs.
#
# Default to enabled when HUMAN_LOGS are enabled so developer-facing
# deployments have immediate visibility into Render API calls.
_log_render_http_default = "true" if HUMAN_LOGS else "false"
LOG_RENDER_HTTP = _env_flag("LOG_RENDER_HTTP", _log_render_http_default)

# When enabled, include response bodies for Render HTTP logs.
# WARNING: This can be very large for log endpoints.
LOG_RENDER_HTTP_BODIES = _env_flag("LOG_RENDER_HTTP_BODIES", "false")

# Append structured extras to provider log lines.
#
# Render log viewers and similar UIs are optimized for humans; emitting raw JSON
# blobs makes logs significantly harder to read. This server therefore formats
# extras as a YAML-like block (no JSON) when appended.
#
# Defaults:
# - When HUMAN_LOGS=true: append extras for tool events (tool_call_*) and for
#   WARNING/ERROR.
# - When HUMAN_LOGS=false: keep extras off by default.
LOG_APPEND_EXTRAS = _env_flag(
    "LOG_APPEND_EXTRAS",
    "true" if HUMAN_LOGS else "false",
)

# Cap appended extras to keep provider log ingestion healthy.
LOG_EXTRAS_MAX_LINES = int(os.environ.get("LOG_EXTRAS_MAX_LINES", "200"))
LOG_EXTRAS_MAX_CHARS = int(os.environ.get("LOG_EXTRAS_MAX_CHARS", "20000"))

# Backwards-compat: deprecated.
LOG_APPEND_EXTRAS_JSON = _env_flag("LOG_APPEND_EXTRAS_JSON", "false")

# Repo mirror diff application can be slow for large diffs. Keep this configurable.
WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS = int(
    os.environ.get("MCP_WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS", "0")
)

ADAPTIV_MCP_GIT_IDENTITY_ENV_VARS = (
    "ADAPTIV_MCP_GIT_AUTHOR_NAME",
    "ADAPTIV_MCP_GIT_AUTHOR_EMAIL",
    "ADAPTIV_MCP_GIT_COMMITTER_NAME",
    "ADAPTIV_MCP_GIT_COMMITTER_EMAIL",
)

DEFAULT_GIT_IDENTITY = {
    "author_name": "Adaptiv MCP",
    "author_email": "adaptiv-mcp@local",
    "committer_name": "Adaptiv MCP",
    "committer_email": "adaptiv-mcp@local",
}

PLACEHOLDER_GIT_IDENTITY: dict[str, str] = {}


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
        explicit_env=os.environ.get("ADAPTIV_MCP_GIT_AUTHOR_NAME"),
        app_value=app_identity.get("name"),
        default_value=DEFAULT_GIT_IDENTITY["author_name"],
    )
    author_email, author_email_source = resolve_value(
        explicit_env=os.environ.get("ADAPTIV_MCP_GIT_AUTHOR_EMAIL"),
        app_value=app_identity.get("email"),
        default_value=DEFAULT_GIT_IDENTITY["author_email"],
    )

    committer_name_env = os.environ.get("ADAPTIV_MCP_GIT_COMMITTER_NAME")
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

    committer_email_env = os.environ.get("ADAPTIV_MCP_GIT_COMMITTER_EMAIL")
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

    placeholder_active = False

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
        "Git identity is using placeholder values. Configure ADAPTIV_MCP_GIT_AUTHOR_NAME, "
        "ADAPTIV_MCP_GIT_AUTHOR_EMAIL, ADAPTIV_MCP_GIT_COMMITTER_NAME, and "
        "ADAPTIV_MCP_GIT_COMMITTER_EMAIL (or set GitHub App metadata) to ensure commits "
        "are attributed correctly."
    ]


LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
# Default to a compact, scannable format.
LOG_FORMAT = os.environ.get(
    "LOG_FORMAT",
    "%(levelname)s | %(name)s | %(message)s",
)

# ANSI color for log level + logger name (intended for developer-tail workflows).
#
# Compatibility:
# - Docs and tool visual logging use ADAPTIV_MCP_LOG_COLOR.
# - Older deployments (and some tests) used LOG_COLOR.
#
# Prefer the prefixed variant when present, but keep LOG_COLOR as a fallback.
_raw_log_color = os.environ.get("ADAPTIV_MCP_LOG_COLOR")
if _raw_log_color is None:
    LOG_COLOR = _env_flag("LOG_COLOR", "true")
else:
    LOG_COLOR = str(_raw_log_color).strip().lower() in ("1", "true", "t", "yes", "y", "on")


class _StructuredFormatter(logging.Formatter):
    """Formatter that appends structured extra fields for provider logs."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting
        # Mutate the record for a clean, developer-facing console format.
        original_levelname = record.levelname
        original_name = record.name

        try:
            if HUMAN_LOGS and LOG_COLOR:
                reset = "\x1b[0m"
                dim = "\x1b[2m"
                red = "\x1b[31m"
                green = "\x1b[32m"
                yellow = "\x1b[33m"
                cyan = "\x1b[36m"

                # Colorize levelname.
                if record.levelno >= logging.ERROR:
                    record.levelname = f"{red}{original_levelname}{reset}"
                elif record.levelno >= logging.WARNING:
                    record.levelname = f"{yellow}{original_levelname}{reset}"
                else:
                    # INFO/DEBUG
                    record.levelname = f"{green}{original_levelname}{reset}"

                # Shorten and lightly colorize logger names.
                name = original_name
                if name.startswith("github_mcp."):
                    name = name[len("github_mcp.") :]
                if name in {"mcp", "mcp_server.decorators", "mcp_server"}:
                    name = "mcp"
                elif name.startswith("tools_workspace"):
                    name = "workspace"
                elif name.startswith("github_client"):
                    name = "github"
                record.name = f"{dim}{cyan}{name}{reset}"
            else:
                # Even without ANSI, shorten the logger name for readability.
                name = original_name
                if name.startswith("github_mcp."):
                    name = name[len("github_mcp.") :]
                if name in {"mcp", "mcp_server.decorators", "mcp_server"}:
                    name = "mcp"
                elif name.startswith("tools_workspace"):
                    name = "workspace"
                elif name.startswith("github_client"):
                    name = "github"
                record.name = name

            base = super().format(record)
        finally:
            record.levelname = original_levelname
            record.name = original_name

        extra_payload = _extract_log_extras(record)
        if not extra_payload:
            return base

        # Keep INFO lines scan-friendly for humans while ensuring key tool/http
        # events are self-contained for debugging in provider logs.
        #
        # NOTE:
        # These are intentionally limited to high-signal events so enabling
        # LOG_APPEND_EXTRAS does not explode log volume.
        always_append_events = {
            # Tool lifecycle events (INFO).
            "tool_call_started",
            "tool_call_completed",
            "tool_call_completed_with_warnings",
            "tool_call_failed",
            # HTTP request lifecycle events emitted by the ASGI middleware.
            "http_request",
            "http_exception",
            # Render client request logs (when enabled).
            "render_http",
        }
        event = getattr(record, "event", None)

        # Do not append an "extras" block for tool events.
        # Tool logs already embed a scan-friendly summary (REQ/RES) and keeping
        # an additional YAML-like block duplicates information and adds noise.
        if isinstance(event, str) and event.startswith("tool_"):
            return base

        severity = getattr(record, "severity", None)
        severity_is_warn_or_error = (
            isinstance(severity, str) and severity.strip().lower() in {"warning", "error"}
        )

        should_append = bool(LOG_APPEND_EXTRAS) and (
            record.levelno >= logging.WARNING
            or severity_is_warn_or_error
            or (isinstance(event, str) and event in always_append_events)
        )

        if not should_append:
            return base

        extra_payload = _sanitize_for_logs(extra_payload)
        extras_block = _format_extras_block(extra_payload)
        if extras_block:
            return f"{base}\n{extras_block}"
        return base


def _format_extras_block(payload: Mapping[str, Any]) -> str:
    """Render log extras as a YAML-like block (no JSON)."""

    if not isinstance(payload, Mapping) or not payload:
        return ""

    # Helper to render scalars safely.
    def scalar(v: object) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        s = str(v)
        # Keep single-line scalars.
        s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        return " ".join(s.split())

    lines: list[str] = []
    max_lines = max(20, int(LOG_EXTRAS_MAX_LINES))
    max_chars = max(2000, int(LOG_EXTRAS_MAX_CHARS))

    def emit(line: str) -> None:
        if len(lines) >= max_lines:
            return
        lines.append(line)

    def walk(key: str, value: object, indent: int) -> None:
        prefix = "  " * indent
        if isinstance(value, Mapping):
            emit(f"{prefix}{key}:")
            for k2, v2 in list(value.items()):
                if len(lines) >= max_lines:
                    break
                walk(str(k2), v2, indent + 1)
            return
        if isinstance(value, list):
            emit(f"{prefix}{key}:")
            for item in value[:50]:
                if len(lines) >= max_lines:
                    break
                if isinstance(item, (Mapping, list)):
                    emit(f"{prefix}  -")
                    if isinstance(item, Mapping):
                        for k2, v2 in list(item.items()):
                            if len(lines) >= max_lines:
                                break
                            walk(str(k2), v2, indent + 2)
                    else:
                        emit(f"{prefix}    - {scalar(item)}")
                else:
                    emit(f"{prefix}  - {scalar(item)}")
            if len(value) > 50 and len(lines) < max_lines:
                emit(f"{prefix}  - … ({len(value) - 50} more)")
            return

        emit(f"{prefix}{key}: {scalar(value)}")

    # Sort for stable output.
    emit("extras:")
    for k, v in sorted(payload.items(), key=lambda kv: str(kv[0])):
        if len(lines) >= max_lines:
            break
        walk(str(k), v, 1)

    out = "\n".join(lines)
    if len(out) > max_chars:
        out = out[: max(0, max_chars - 1)] + "…"
    return out


_STANDARD_LOG_FIELDS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys())


class _InfoOnlyFilter(logging.Filter):
    """Allow only INFO log records.

    This repo is intentionally configured to emit a single log level in provider
    streams.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - matches logging.Filter
        return record.levelno == logging.INFO


class _UvicornHealthzFilter(logging.Filter):
    """Suppress noisy health check access logs from uvicorn."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - matches logging.Filter
        try:
            message = record.getMessage()
        except Exception:
            return True
        return "/healthz" not in message


def _extract_log_extras(record: logging.LogRecord) -> dict[str, object]:
    extras: dict[str, object] = {}

    # NOTE:
    # The formatter mutates the record by injecting fields like `asctime` and
    # computing `message` from msg/args. When we later append structured extras
    # using record.__dict__, those injected fields can be picked up as extras and
    # cause duplication and extremely noisy logs.
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
    console_handler.setLevel(logging.INFO)
    console_handler.addFilter(_InfoOnlyFilter())

    logging.basicConfig(
        level=logging.INFO,
        handlers=[console_handler],
        force=True,
    )

    # Uvicorn CLI applies its own logging configuration. We rebind uvicorn loggers
    # to the root handler so the output format is consistent (and colorized).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

    # Reduce noisy framework logs in provider log streams.
    for noisy in (
        "mcp",
        "mcp.server",
        "mcp.server.lowlevel.server",
        "httpx",
        "httpcore",
    ):
        logging.getLogger(noisy).setLevel(logging.INFO)

    # Keep access logs off by default (they include request IDs / IPs and are very noisy).
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").addFilter(_UvicornHealthzFilter())

    root._github_mcp_configured = True


_configure_logging()

BASE_LOGGER = logging.getLogger("github_mcp")
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
    "ADAPTIV_MCP_GIT_IDENTITY_ENV_VARS",
    "GITHUB_TOKEN_ENV_VARS",
    "GITHUB_LOGGER",
    "GITHUB_PAT",
    "HTTPX_MAX_CONNECTIONS",
    "HTTPX_MAX_KEEPALIVE",
    "HTTPX_TIMEOUT",
    "LOG_APPEND_EXTRAS",
    "LOG_EXTRAS_MAX_LINES",
    "LOG_EXTRAS_MAX_CHARS",
    "LOG_RENDER_HTTP",
    "LOG_RENDER_HTTP_BODIES",
    "LOG_TOOL_CALLS",
    "LOG_TOOL_CALL_STARTS",
    "LOG_HTTP_REQUESTS",
    "LOG_INLINE_CONTEXT",
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
    "format_log_context",
    "shorten_token",
    "snapshot_request_context",
    "summarize_request_context",
]
