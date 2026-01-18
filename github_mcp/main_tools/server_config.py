from __future__ import annotations

import os
from typing import Any

import github_mcp.server as server
from github_mcp.config import (
    FETCH_FILES_CONCURRENCY,
    GIT_AUTHOR_EMAIL,
    GIT_AUTHOR_NAME,
    GIT_COMMITTER_EMAIL,
    GIT_COMMITTER_NAME,
    GIT_IDENTITY_PLACEHOLDER_ACTIVE,
    GIT_IDENTITY_SOURCES,
    GITHUB_API_BASE,
    GITHUB_TOKEN_ENV_VARS,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    MAX_CONCURRENCY,
    SANDBOX_CONTENT_BASE_URL,
    git_identity_warnings,
)
from github_mcp.exceptions import GitHubAPIError, GitHubAuthError
from github_mcp.render_api import _get_optional_render_token
from github_mcp.server import (
    CONTROLLER_DEFAULT_BRANCH,
    CONTROLLER_REPO,
    _github_request,
)
from github_mcp.utils import REPO_DEFAULTS, REPO_DEFAULTS_PARSE_ERROR, _get_main_module


async def get_server_config() -> dict[str, Any]:
    """Return a safe summary of MCP connector and runtime settings."""

    config_payload = {
        "write_allowed": bool(server.WRITE_ALLOWED),
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
        "git_identity": {
            "author_name": GIT_AUTHOR_NAME,
            "author_email": GIT_AUTHOR_EMAIL,
            "committer_name": GIT_COMMITTER_NAME,
            "committer_email": GIT_COMMITTER_EMAIL,
            "sources": GIT_IDENTITY_SOURCES,
            "placeholder_active": GIT_IDENTITY_PLACEHOLDER_ACTIVE,
        },
        "sandbox": {
            "sandbox_content_base_url_configured": bool(SANDBOX_CONTENT_BASE_URL),
        },
        "environment": {
            "github_token_present": any(os.environ.get(name) for name in GITHUB_TOKEN_ENV_VARS),
            "render_token_present": bool(_get_optional_render_token()),
        },
    }
    warnings: list[str] = []
    if REPO_DEFAULTS_PARSE_ERROR:
        warnings.append(REPO_DEFAULTS_PARSE_ERROR)
    warnings.extend(git_identity_warnings())
    if warnings:
        config_payload["warnings"] = warnings

    return config_payload


async def get_repo_defaults(full_name: str | None = None) -> dict[str, Any]:
    """Return default configuration for a GitHub repository."""

    main_mod = _get_main_module()
    controller_repo = getattr(main_mod, "CONTROLLER_REPO", CONTROLLER_REPO)
    controller_default_branch = getattr(
        main_mod, "CONTROLLER_DEFAULT_BRANCH", CONTROLLER_DEFAULT_BRANCH
    )

    if full_name is None:
        full_name = controller_repo

    # Repo-specific defaults. Fall back to global defaults when not configured.
    defaults = REPO_DEFAULTS.get(full_name) or {}

    # Determine default branch. Prefer configured controller default branch for the controller repo.
    if full_name == controller_repo:
        default_branch = controller_default_branch
    else:
        # Fetch from GitHub if not present in defaults.
        default_branch = defaults.get("default_branch")
        if not default_branch:
            try:
                # Minimal request for repo metadata
                repo_info = await _github_request("GET", f"/repos/{full_name}")
                default_branch = (
                    (repo_info.get("json") or {}).get("default_branch")
                    if isinstance(repo_info, dict)
                    else None
                )
            except GitHubAuthError:
                # If auth is missing/invalid, fall back to a common convention
                default_branch = "main"
            except GitHubAPIError:
                default_branch = "main"

    return {
        "full_name": full_name,
        "default_branch": default_branch or "main",
        "defaults": defaults,
    }
