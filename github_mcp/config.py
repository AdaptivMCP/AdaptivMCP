"""Configuration and logging helpers for the GitHub MCP server."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time

from github_mcp.mcp_server.schemas import _jsonable

# Custom log levels
# ------------------------------------------------------------------------------
#
# CHAT: user-facing, chat-like progress messages intended to keep the human
# informed while long tools run.
# DETAILED: verbose operational logging that is more detailed than INFO but less
# noisy than full DEBUG.

DETAILED_LEVEL = 15
CHAT_LEVEL = 25


def _install_custom_log_levels() -> None:
    # Make them visible as logging.CHAT / logging.DETAILED, etc.
    if not hasattr(logging, "DETAILED"):
        logging.addLevelName(DETAILED_LEVEL, "DETAILED")
        setattr(logging, "DETAILED", DETAILED_LEVEL)

    if not hasattr(logging, "CHAT"):
        logging.addLevelName(CHAT_LEVEL, "CHAT")
        setattr(logging, "CHAT", CHAT_LEVEL)

    # Add Logger helpers: logger.chat(...), logger.detailed(...)
    if not hasattr(logging.Logger, "detailed"):

        def detailed(self: logging.Logger, msg, *args, **kwargs):
            if self.isEnabledFor(DETAILED_LEVEL):
                self._log(DETAILED_LEVEL, msg, args, **kwargs)

        logging.Logger.detailed = detailed  # type: ignore[attr-defined]

    if not hasattr(logging.Logger, "chat"):

        def chat(self: logging.Logger, msg, *args, **kwargs):
            if self.isEnabledFor(CHAT_LEVEL):
                self._log(CHAT_LEVEL, msg, args, **kwargs)

        logging.Logger.chat = chat  # type: ignore[attr-defined]


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

    if name == "DETAILED":
        return DETAILED_LEVEL
    if name == "CHAT":
        return CHAT_LEVEL

    return getattr(logging, name, logging.INFO)


_install_custom_log_levels()

# Configuration and globals
# ------------------------------------------------------------------------------

GITHUB_TOKEN_ENV_VARS = ("GITHUB_PAT", "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_OAUTH_TOKEN")
GITHUB_PAT = os.environ.get("GITHUB_PAT")
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_API_BASE_URL = GITHUB_API_BASE

SANDBOX_CONTENT_BASE_URL = os.environ.get("SANDBOX_CONTENT_BASE_URL")

# Base directory for persistent workspaces used by terminal_command and related tools.
# This keeps cloned repositories stable across tool invocations so installations
# and edits survive until explicitly reset or deleted.
WORKSPACE_BASE_DIR = os.environ.get(
    "MCP_WORKSPACE_BASE_DIR",
    os.path.join(tempfile.gettempdir(), "mcp-github-workspaces"),
)

HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", 150))
GITHUB_REQUEST_TIMEOUT_SECONDS = HTTPX_TIMEOUT
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", 300))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", 200))

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", 80))
FETCH_FILES_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", "80"))
FILE_CACHE_MAX_ENTRIES = int(os.environ.get("FILE_CACHE_MAX_ENTRIES", "500"))
FILE_CACHE_MAX_BYTES = int(os.environ.get("FILE_CACHE_MAX_BYTES", "52428800"))
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

GITHUB_MCP_GIT_IDENTITY_ENV_VARS = (
    "GITHUB_MCP_GIT_AUTHOR_NAME",
    "GITHUB_MCP_GIT_AUTHOR_EMAIL",
    "GITHUB_MCP_GIT_COMMITTER_NAME",
    "GITHUB_MCP_GIT_COMMITTER_EMAIL",
)

DEFAULT_GIT_IDENTITY = {
    "author_name": "Ally",
    "author_email": "ally@example.com",
    "committer_name": "Ally",
    "committer_email": "ally@example.com",
}


def _slugify_app_name(value: str | None) -> str | None:
    if not value:
        return None
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or None


def _resolve_app_identity() -> dict[str, str] | None:
    app_name = os.environ.get("GITHUB_APP_NAME")
    app_slug = os.environ.get("GITHUB_APP_SLUG") or _slugify_app_name(app_name)
    app_id = os.environ.get("GITHUB_APP_ID") or os.environ.get(
        "GITHUB_APP_INSTALLATION_ID"
    )

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
        legacy_env: str | None,
        app_value: str | None,
        default_value: str,
    ) -> tuple[str, str]:
        if explicit_env:
            return explicit_env, "explicit_env"
        if legacy_env:
            return legacy_env, "legacy_env"
        if app_value:
            return app_value, "app_metadata"
        return default_value, "default_placeholder"

    author_name, author_name_source = resolve_value(
        explicit_env=os.environ.get("GITHUB_MCP_GIT_AUTHOR_NAME"),
        legacy_env=os.environ.get("GIT_AUTHOR_NAME"),
        app_value=app_identity.get("name"),
        default_value=DEFAULT_GIT_IDENTITY["author_name"],
    )
    author_email, author_email_source = resolve_value(
        explicit_env=os.environ.get("GITHUB_MCP_GIT_AUTHOR_EMAIL"),
        legacy_env=os.environ.get("GIT_AUTHOR_EMAIL"),
        app_value=app_identity.get("email"),
        default_value=DEFAULT_GIT_IDENTITY["author_email"],
    )

    committer_name_env = os.environ.get("GITHUB_MCP_GIT_COMMITTER_NAME")
    legacy_committer_name = os.environ.get("GIT_COMMITTER_NAME")
    committer_name = None
    committer_name_source = None
    if committer_name_env:
        committer_name = committer_name_env
        committer_name_source = "explicit_env"
    elif legacy_committer_name:
        committer_name = legacy_committer_name
        committer_name_source = "legacy_env"
    elif app_identity.get("name"):
        committer_name = app_identity.get("name")
        committer_name_source = "app_metadata"
    else:
        committer_name = author_name
        committer_name_source = "author_fallback"

    committer_email_env = os.environ.get("GITHUB_MCP_GIT_COMMITTER_EMAIL")
    legacy_committer_email = os.environ.get("GIT_COMMITTER_EMAIL")
    committer_email = None
    committer_email_source = None
    if committer_email_env:
        committer_email = committer_email_env
        committer_email_source = "explicit_env"
    elif legacy_committer_email:
        committer_email = legacy_committer_email
        committer_email_source = "legacy_env"
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

    placeholder_active = any(
        source == "default_placeholder" for source in sources.values()
    )

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

# Upper bounds for unified diffs printed to stdout logs for write tools.
WRITE_DIFF_LOG_MAX_LINES = int(os.environ.get("WRITE_DIFF_LOG_MAX_LINES", "0"))


def _parse_tool_list(value: str) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


DEFAULT_TOOL_DENYLIST = {}


def _resolve_tool_denylist() -> set[str]:
    override = os.environ.get("MCP_TOOL_DENYLIST")
    if override is None or not override.strip():
        return set(DEFAULT_TOOL_DENYLIST)
    normalized = override.strip().lower()
    if normalized in {"none", "off", "false", "0"}:
        return set()
    return _parse_tool_list(override)


TOOL_DENYLIST = _resolve_tool_denylist()

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_STYLE = os.environ.get("LOG_STYLE", "color").lower()

# Default to a compact, scannable format.
LOG_FORMAT = os.environ.get(
    "LOG_FORMAT",
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


class _ColorFormatter(logging.Formatter):
    """Level-colored formatter for stdout logs.

    Render's log viewer can display ANSI sequences; if it doesn't, the output
    will still remain readable.
    """

    _C = {
        "DEBUG": "\x1b[36m",  # cyan
        "DETAILED": "\x1b[36m",  # cyan
        "INFO": "\x1b[32m",  # green
        "CHAT": "\x1b[34m",  # blue
        "WARNING": "\x1b[33m",  # yellow
        "ERROR": "\x1b[31m",  # red
        "CRITICAL": "\x1b[35m",  # magenta
        "RESET": "\x1b[0m",
    }

    def __init__(self, fmt: str, *, use_color: bool) -> None:
        super().__init__(fmt)
        self._use_color = bool(use_color)

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - formatting
        levelname = record.levelname
        if self._use_color and levelname in self._C:
            record.levelname = f"{self._C[levelname]}{levelname}{self._C['RESET']}"
        try:
            base = super().format(record)
            extra_payload = _extract_log_extras(record)
            if extra_payload:
                # CHAT logs are the primary human console surface in Render; keep them message-only.
                if levelname == "CHAT":
                    return base
                extra_json = json.dumps(
                    extra_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                return f"{base} | data={extra_json}"
            return base
        finally:
            record.levelname = levelname


_STANDARD_LOG_FIELDS = set(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
)


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

    use_color = LOG_STYLE in {"color", "ansi", "colored"}

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(_ColorFormatter(LOG_FORMAT, use_color=use_color))

    logging.basicConfig(
        level=_resolve_log_level(LOG_LEVEL),
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
        logging.getLogger(noisy).setLevel(logging.WARNING)

    setattr(root, "_github_mcp_configured", True)


_configure_logging()

BASE_LOGGER = logging.getLogger("github_mcp")
GITHUB_LOGGER = logging.getLogger("github_mcp.github_client")
TOOLS_LOGGER = logging.getLogger("github_mcp.tools")

SERVER_START_TIME = time.time()

__all__ = [
    "BASE_LOGGER",
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
    "MAX_CONCURRENCY",
    "SERVER_START_TIME",
    "CHAT_LEVEL",
    "DETAILED_LEVEL",
    "TOOLS_LOGGER",
    "WORKSPACE_BASE_DIR",
    "SANDBOX_CONTENT_BASE_URL",
    "git_identity_warnings",
]
