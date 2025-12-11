"""Configuration and logging helpers for the GitHub MCP server."""

from __future__ import annotations

import logging
import os
import tempfile
import time

# Configuration and globals
# ------------------------------------------------------------------------------

GITHUB_PAT = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_API_BASE_URL = GITHUB_API_BASE

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
# For this controller we default to *no* machine-side truncation and let the host
# environment enforce any transport limits. Deployments that want smaller payloads
# can still override these via environment variables.
TOOL_STDOUT_MAX_CHARS = int(os.environ.get("TOOL_STDOUT_MAX_CHARS", "0"))
TOOL_STDERR_MAX_CHARS = int(os.environ.get("TOOL_STDERR_MAX_CHARS", "0"))
TOOL_STDIO_COMBINED_MAX_CHARS = int(os.environ.get("TOOL_STDIO_COMBINED_MAX_CHARS", "0"))

# Soft limit for run_command.command length to discourage huge inline scripts.
RUN_COMMAND_MAX_CHARS = int(os.environ.get("RUN_COMMAND_MAX_CHARS", "8000"))

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.environ.get(
    "LOG_FORMAT",
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
)

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
    "GITHUB_LOGGER",
    "GITHUB_PAT",
    "HTTPX_MAX_CONNECTIONS",
    "HTTPX_MAX_KEEPALIVE",
    "HTTPX_TIMEOUT",
    "MAX_CONCURRENCY",
    "RUN_COMMAND_MAX_CHARS",
    "SERVER_START_TIME",
    "TOOLS_LOGGER",
    "TOOL_STDERR_MAX_CHARS",
    "TOOL_STDIO_COMBINED_MAX_CHARS",
    "TOOL_STDOUT_MAX_CHARS",
    "WORKSPACE_BASE_DIR",
]
