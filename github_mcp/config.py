"""Configuration and logging helpers for the GitHub MCP server."""

from __future__ import annotations

import logging
import os
import tempfile
import time
from collections import deque

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

GITHUB_PAT = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_API_BASE_URL = GITHUB_API_BASE

# Render Public API (optional, for provider-side logs/metrics).
RENDER_API_BASE = os.environ.get("RENDER_API_BASE", "https://api.render.com/v1")
RENDER_API_KEY = os.environ.get("RENDER_API_KEY") or os.environ.get("RENDER_API_TOKEN")
# Default Render resource/service id for render_* observability tools.
RENDER_DEFAULT_RESOURCE = os.environ.get("RENDER_RESOURCE") or os.environ.get("RENDER_SERVICE_ID")
RENDER_OWNER_ID = os.environ.get("RENDER_OWNER_ID") or os.environ.get("RENDER_OWNER")

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
FETCH_FILES_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", MAX_CONCURRENCY))
FILE_CACHE_MAX_ENTRIES = int(os.environ.get("FILE_CACHE_MAX_ENTRIES", "500"))
FILE_CACHE_MAX_BYTES = int(os.environ.get("FILE_CACHE_MAX_BYTES", "52428800"))

GIT_AUTHOR_NAME = os.environ.get("GIT_AUTHOR_NAME", "Ally")
GIT_AUTHOR_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "ally@example.com")
GIT_COMMITTER_NAME = os.environ.get("GIT_COMMITTER_NAME", GIT_AUTHOR_NAME)
GIT_COMMITTER_EMAIL = os.environ.get("GIT_COMMITTER_EMAIL", GIT_AUTHOR_EMAIL)

# Upper bounds for tool stdout/stderr payloads returned to the connector. These
# can be tuned via environment variables; set to 0 or a negative value to disable
# truncation if a deployment prefers full logs at the cost of larger responses.
#
# Defaults now prefer no truncation so the connector can relay the complete
# output unless a deployment explicitly opts into bounds via environment
# variables.
TOOL_STDOUT_MAX_CHARS = int(os.environ.get("TOOL_STDOUT_MAX_CHARS", "0"))
TOOL_STDERR_MAX_CHARS = int(os.environ.get("TOOL_STDERR_MAX_CHARS", "0"))
TOOL_STDIO_COMBINED_MAX_CHARS = int(os.environ.get("TOOL_STDIO_COMBINED_MAX_CHARS", "0"))

# Upper bounds for unified diffs printed to stdout logs for write tools.
# These are separate from TOOL_STDOUT_MAX_CHARS (tool return payload truncation).
WRITE_DIFF_LOG_MAX_LINES = int(os.environ.get("WRITE_DIFF_LOG_MAX_LINES", "0"))
WRITE_DIFF_LOG_MAX_CHARS = int(os.environ.get("WRITE_DIFF_LOG_MAX_CHARS", "0"))

# Soft limit for run_command.command length to discourage huge inline scripts.
# Defaults to unbounded unless overridden by deployment configuration.
RUN_COMMAND_MAX_CHARS = int(os.environ.get("RUN_COMMAND_MAX_CHARS", "0"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_STYLE = os.environ.get("LOG_STYLE", "color").lower()

# Default to a compact, scannable format.
LOG_FORMAT = os.environ.get(
    "LOG_FORMAT",
    "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

# Use a non-colored formatter for in-memory logs (these often show up in JSON
# tool results and should stay plain text).
LOG_FORMAT_PLAIN = os.environ.get("LOG_FORMAT_PLAIN", LOG_FORMAT)


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
            return super().format(record)
        finally:
            record.levelname = levelname


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

ERROR_LOG_CAPACITY = int(os.environ.get("MCP_ERROR_LOG_CAPACITY", "200"))
LOG_RECORD_CAPACITY = int(os.environ.get("MCP_LOG_RECORD_CAPACITY", "500"))


class _InMemoryErrorLogHandler(logging.Handler):
    """Capture recent error-level log records in memory for MCP tools."""

    def __init__(self, capacity: int = 200) -> None:
        super().__init__(level=logging.ERROR)
        self._capacity = int(capacity)
        self._formatter = logging.Formatter(LOG_FORMAT_PLAIN)
        if self._capacity <= 0:
            self._records: list[dict[str, object]] = []
        else:
            self._records = deque(maxlen=max(1, self._capacity))

    @property
    def records(self) -> list[dict[str, object]]:
        return list(self._records)

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        try:
            message = self._formatter.format(record)
        except Exception:  # noqa: BLE001
            message = record.getMessage()

        payload = {
            "logger": record.name,
            "level": record.levelname,
            "message": message,
            "created": record.created,
            "tool_name": getattr(record, "tool_name", None),
            "call_id": getattr(record, "call_id", None),
            "tool_context": getattr(record, "tool_context", None),
            "tool_error_type": getattr(record, "tool_error_type", None),
            "tool_error_message": getattr(record, "tool_error_message", None),
            "tool_error_origin": getattr(record, "tool_error_origin", None),
            "tool_error_category": getattr(record, "tool_error_category", None),
        }

        self._records.append(payload)


ERROR_LOG_HANDLER = _InMemoryErrorLogHandler(capacity=ERROR_LOG_CAPACITY)
BASE_LOGGER.addHandler(ERROR_LOG_HANDLER)


class _InMemoryLogHandler(logging.Handler):
    """Capture recent log records in memory for MCP diagnostics tools."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__(level=DETAILED_LEVEL)
        self._capacity = int(capacity)
        self._formatter = logging.Formatter(LOG_FORMAT_PLAIN)
        if self._capacity <= 0:
            self._records: list[dict[str, object]] = []
        else:
            self._records = deque(maxlen=max(1, self._capacity))

    @property
    def records(self) -> list[dict[str, object]]:
        return list(self._records)

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
        if not record.name.startswith("github_mcp"):
            return

        try:
            message = self._formatter.format(record)
        except Exception:  # noqa: BLE001
            message = record.getMessage()

        payload = {
            "logger": record.name,
            "level": record.levelname,
            "message": message,
            "created": record.created,
            "tool_name": getattr(record, "tool_name", None),
            "call_id": getattr(record, "call_id", None),
            "repo": getattr(record, "repo", None),
            "ref": getattr(record, "ref", None),
            "path": getattr(record, "path", None),
            "status": getattr(record, "status", None),
            "write_action": getattr(record, "write_action", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "tags": getattr(record, "tags", None),
            "error_category": getattr(record, "error_category", None),
            "error_origin": getattr(record, "error_origin", None),
        }

        self._records.append(payload)


LOG_RECORD_HANDLER = _InMemoryLogHandler(capacity=LOG_RECORD_CAPACITY)
BASE_LOGGER.addHandler(LOG_RECORD_HANDLER)

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
    "GITHUB_LOGGER",
    "GITHUB_PAT",
    "RENDER_API_BASE",
    "RENDER_API_KEY",
    "RENDER_DEFAULT_RESOURCE",
    "HTTPX_MAX_CONNECTIONS",
    "HTTPX_MAX_KEEPALIVE",
    "HTTPX_TIMEOUT",
    "MAX_CONCURRENCY",
    "RUN_COMMAND_MAX_CHARS",
    "SERVER_START_TIME",
    "CHAT_LEVEL",
    "DETAILED_LEVEL",
    "TOOLS_LOGGER",
    "TOOL_STDERR_MAX_CHARS",
    "TOOL_STDIO_COMBINED_MAX_CHARS",
    "TOOL_STDOUT_MAX_CHARS",
    "WORKSPACE_BASE_DIR",
    "ERROR_LOG_HANDLER",
    "ERROR_LOG_CAPACITY",
    "LOG_RECORD_HANDLER",
    "LOG_RECORD_CAPACITY",
]
