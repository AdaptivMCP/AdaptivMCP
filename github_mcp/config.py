"""Configuration and logging helpers for the GitHub MCP server."""

from __future__ import annotations

import json
import logging
import os
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
    if not hasattr(logging, 'DETAILED'):
        logging.addLevelName(DETAILED_LEVEL, 'DETAILED')
        setattr(logging, 'DETAILED', DETAILED_LEVEL)

    if not hasattr(logging, 'CHAT'):
        logging.addLevelName(CHAT_LEVEL, 'CHAT')
        setattr(logging, 'CHAT', CHAT_LEVEL)

    # Add Logger helpers: logger.chat(...), logger.detailed(...)
    if not hasattr(logging.Logger, 'detailed'):
        def detailed(self: logging.Logger, msg, *args, **kwargs):
            if self.isEnabledFor(DETAILED_LEVEL):
                self._log(DETAILED_LEVEL, msg, args, **kwargs)
        logging.Logger.detailed = detailed  # type: ignore[attr-defined]

    if not hasattr(logging.Logger, 'chat'):
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
    if name.lstrip('-').isdigit():
        try:
            return int(name)
        except Exception:
            return logging.INFO

    if name == 'DETAILED':
        return DETAILED_LEVEL
    if name == 'CHAT':
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

# Base directory for persistent workspaces used by run_command and related tools.
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

GIT_AUTHOR_NAME = os.environ.get("GIT_AUTHOR_NAME", "Ally")
GIT_AUTHOR_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "ally@example.com")
GIT_COMMITTER_NAME = os.environ.get("GIT_COMMITTER_NAME", "Ally")
GIT_COMMITTER_EMAIL = os.environ.get("GIT_COMMITTER_EMAIL", "ally@example.com")

# Upper bounds for unified diffs printed to stdout logs for write tools.
WRITE_DIFF_LOG_MAX_LINES = int(os.environ.get("WRITE_DIFF_LOG_MAX_LINES", "0"))


def _parse_tool_list(value: str) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


DEFAULT_TOOL_DENYLIST = {
}


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
                    extra_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
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
    "GITHUB_API_BASE",
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
]
