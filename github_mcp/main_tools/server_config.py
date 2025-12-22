from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional

import github_mcp.server as server
from github_mcp.config import (
    FETCH_FILES_CONCURRENCY,
    GIT_AUTHOR_EMAIL,
    GIT_AUTHOR_NAME,
    GIT_COMMITTER_EMAIL,
    GIT_COMMITTER_NAME,
    GITHUB_API_BASE,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    MAX_CONCURRENCY,
)
from github_mcp.exceptions import GitHubAPIError, GitHubAuthError
from github_mcp.server import CONTROLLER_DEFAULT_BRANCH, CONTROLLER_REPO, _github_request
from github_mcp.utils import REPO_DEFAULTS


async def get_server_config() -> Dict[str, Any]:
    """Return a safe summary of MCP connector and runtime settings."""

    return {
        "write_allowed": True,
        "github_api_base": GITHUB_API_BASE,
        "http": {
            "timeout": HTTPX_TIMEOUT,
            "max_connections": HTTPX_MAX_CONNECTIONS,
            "max_keepalive": HTTPX_MAX_KEEPALIVE,
        },
        "concurrency": {
            "max_concurrency": MAX_CONCURRENCY,
            "fetch_files_concurrency": FETCH_FILES_CONCURRENCY,
        },
        "approval_policy": {
            "notes": (
                "Server-side write gating has been removed; write-tagged tools always run. "
                "The authorize_write_actions tool remains for compatibility but no longer blocks."
            ),
            "toggle_tool": "authorize_write_actions",
        },
        "git_identity": {
            "author_name": GIT_AUTHOR_NAME,
            "author_email": GIT_AUTHOR_EMAIL,
            "committer_name": GIT_COMMITTER_NAME,
            "committer_email": GIT_COMMITTER_EMAIL,
        },
        "sandbox": {
            "sandbox_content_base_url_configured": bool(os.environ.get("SANDBOX_CONTENT_BASE_URL")),
        },
        "environment": {
            "github_token_present": bool(os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")),
        },
    }


def validate_json_string(raw: str) -> Dict[str, Any]:
    """Validate a JSON string and report parse status and errors."""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        context_window = 20
        start = max(0, exc.pos - context_window)
        end = min(len(raw), exc.pos + context_window)

        line_start = raw.rfind("\n", 0, exc.pos) + 1
        line_end = raw.find("\n", exc.pos)
        if line_end == -1:
            line_end = len(raw)

        line_text = raw[line_start:line_end]
        caret_prefix = " " * (exc.colno - 1)
        pointer = f"{caret_prefix}^"

        return {
            "valid": False,
            "error": exc.msg,
            "line": exc.lineno,
            "column": exc.colno,
            "position": exc.pos,
            "snippet": raw[start:end],
            "line_snippet": line_text,
            "pointer": pointer,
        }

    normalized = json.dumps(
        parsed,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )

    return {
        "valid": True,
        "parsed": parsed,
        "parsed_type": type(parsed).__name__,
        "normalized": normalized,
        "normalized_pretty": json.dumps(
            parsed,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
    }


async def get_repo_defaults(full_name: Optional[str] = None) -> Dict[str, Any]:
    """Return default configuration for a GitHub repository."""

    main_mod = sys.modules.get("main")
    controller_repo = getattr(main_mod, "CONTROLLER_REPO", CONTROLLER_REPO)
    controller_default_branch = getattr(
        main_mod, "CONTROLLER_DEFAULT_BRANCH", CONTROLLER_DEFAULT_BRANCH
    )

    repo = full_name or controller_repo

    request_fn = getattr(main_mod, "_github_request", _github_request)

    try:
        data = await request_fn("GET", f"/repos/{repo}")
        payload = data.get("json") or {}
        default_branch = payload.get("default_branch") or controller_default_branch
    except (GitHubAuthError, GitHubAPIError):
        repo_defaults = REPO_DEFAULTS.get(repo)
        default_branch = (repo_defaults or {}).get("default_branch", controller_default_branch)

    return {
        "defaults": {
            "full_name": repo,
            "default_branch": default_branch,
        }
    }

