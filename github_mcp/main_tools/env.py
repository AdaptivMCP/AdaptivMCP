from __future__ import annotations

import os
import subprocess
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional


from ._main import _main
from github_mcp.config import (
    GIT_AUTHOR_EMAIL,
    GIT_AUTHOR_NAME,
    GIT_COMMITTER_EMAIL,
    GIT_COMMITTER_NAME,
    GIT_IDENTITY_PLACEHOLDER_ACTIVE,
    GIT_IDENTITY_SOURCES,
    GITHUB_MCP_GIT_IDENTITY_ENV_VARS,
    GITHUB_TOKEN_ENV_VARS,
    RENDER_TOKEN_ENV_VARS,
)
from github_mcp.render_api import _get_optional_render_token


def _find_repo_root(start: Path) -> Path | None:
    """Best-effort locate the git repo root for this running code."""

    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _get_controller_revision_info() -> Dict[str, Any]:
    """Return best-effort controller revision metadata.

    In some deploy environments, the `.git` directory may not exist.
    """

    info: Dict[str, Any] = {}

    try:
        repo_root = _find_repo_root(Path(__file__).resolve())
        git_bin = shutil.which("git")
        if repo_root is not None and git_bin:
            sha = subprocess.check_output(
                [git_bin, "rev-parse", "HEAD"], cwd=repo_root, text=True
            ).strip()
            info["git_commit"] = sha
            branch = subprocess.check_output(
                [git_bin, "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, text=True
            ).strip()
            info["git_branch"] = branch
    except Exception:
        # Never fail env validation because git metadata is unavailable.
        pass

    return info


async def validate_environment() -> Dict[str, Any]:
    """Check environment settings for GitHub and Render and report problems."""

    m = _main()

    checks: List[Dict[str, Any]] = []
    status = "ok"

    def add_check(
        name: str, level: str, message: str, details: Optional[Dict[str, Any]] = None
    ) -> None:
        nonlocal status
        if details is None:
            details = {}
        checks.append(
            {
                "name": name,
                "level": level,
                "message": message,
                "details": details,
            }
        )
        if level == "error":
            status = "error"
        elif level == "warning" and status != "error":
            status = "warning"

    # GitHub token presence/shape
    raw_token = None
    token_env_var = None
    for env_var in GITHUB_TOKEN_ENV_VARS:
        candidate = os.environ.get(env_var)
        if candidate is not None:
            raw_token = candidate
            token_env_var = env_var
            break

    if raw_token is None:
        add_check(
            "github_token",
            "error",
            "GitHub token is not set",
            {"env_vars": list(GITHUB_TOKEN_ENV_VARS)},
        )
        token_ok = False
    elif not raw_token.strip():
        add_check(
            "github_token",
            "error",
            "GitHub token environment variable is set but empty",
            {"env_var": token_env_var} if token_env_var else {},
        )
        token_ok = False
    else:
        add_check(
            "github_token",
            "ok",
            "GitHub token environment variable is set",
            {"env_var": token_env_var, "length": len(raw_token)},
        )
        token_ok = True

    # Controller repo/branch config
    controller_repo = os.environ.get("GITHUB_MCP_CONTROLLER_REPO") or m.CONTROLLER_REPO
    controller_branch = (
        os.environ.get("GITHUB_MCP_CONTROLLER_BRANCH") or m.CONTROLLER_DEFAULT_BRANCH
    )

    add_check(
        "controller_branch_config",
        "ok",
        "Controller branch is configured",
        {
            "value": controller_branch,
            "env_var": (
                "GITHUB_MCP_CONTROLLER_BRANCH"
                if os.environ.get("GITHUB_MCP_CONTROLLER_BRANCH") is not None
                else None
            ),
        },
    )

    add_check(
        "controller_revision",
        "ok",
        "Controller revision metadata (best-effort)",
        _get_controller_revision_info(),
    )

    # Git identity env vars / placeholders.
    identity_envs = {name: os.environ.get(name) for name in GITHUB_MCP_GIT_IDENTITY_ENV_VARS}
    configured_identity_envs = [
        name for name, value in identity_envs.items() if value and value.strip()
    ]

    identity_details = {
        "explicit_env_vars": configured_identity_envs,
        "sources": GIT_IDENTITY_SOURCES,
        "effective": {
            "author_name": GIT_AUTHOR_NAME,
            "author_email": GIT_AUTHOR_EMAIL,
            "committer_name": GIT_COMMITTER_NAME,
            "committer_email": GIT_COMMITTER_EMAIL,
        },
    }

    if GIT_IDENTITY_PLACEHOLDER_ACTIVE:
        add_check(
            "git_identity_env",
            "warning",
            "Git identity is using placeholder values; configure explicit identity env vars",
            identity_details,
        )
    else:
        add_check(
            "git_identity_env",
            "ok",
            "Git identity is configured",
            identity_details,
        )

    # HTTP / concurrency config (always informational; defaults are fine).
    add_check(
        "http_config",
        "ok",
        "HTTP client configuration resolved",
        {
            "github_api_base": m.GITHUB_API_BASE,
            "timeout": m.HTTPX_TIMEOUT,
            "max_connections": m.HTTPX_MAX_CONNECTIONS,
            "max_keepalive": m.HTTPX_MAX_KEEPALIVE,
        },
    )
    add_check(
        "concurrency_config",
        "ok",
        "Concurrency settings resolved",
        {
            "max_concurrency": m.MAX_CONCURRENCY,
            "fetch_files_concurrency": m.FETCH_FILES_CONCURRENCY,
        },
    )

    # Remote validation for controller repo/branch, only if token is usable.
    if token_ok:
        repo_payload: Dict[str, Any] = {}
        try:
            repo_response = await m._github_request("GET", f"/repos/{controller_repo}")
            if isinstance(repo_response.get("json"), dict):
                repo_payload = repo_response.get("json", {})
        except Exception as exc:  # pragma: no cover - defensive
            add_check(
                "controller_repo_remote",
                "error",
                "Controller repository does not exist or is not accessible",
                {
                    "full_name": controller_repo,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        else:
            add_check(
                "controller_repo_remote",
                "ok",
                "Controller repository exists and is accessible",
                {"full_name": controller_repo},
            )

            permissions = {}
            if isinstance(repo_payload, dict):
                permissions = repo_payload.get("permissions") or {}

            push_allowed = permissions.get("push") if isinstance(permissions, dict) else None
            if push_allowed is True:
                add_check(
                    "controller_repo_push_permission",
                    "ok",
                    "GitHub token can push to the controller repository",
                    {"full_name": controller_repo},
                )
            elif push_allowed is False:
                add_check(
                    "controller_repo_push_permission",
                    "error",
                    "GitHub token lacks push permission to the controller repository; write tools will fail with 403 errors",
                    {"full_name": controller_repo, "permissions": permissions},
                )
            else:
                add_check(
                    "controller_repo_push_permission",
                    "warning",
                    "Could not confirm push permission for the controller repository; ensure the token can push before using commit or push tools",
                    {"full_name": controller_repo, "permissions": permissions},
                )

        try:
            await m._github_request(
                "GET",
                f"/repos/{controller_repo}/branches/{controller_branch}",
            )
        except Exception as exc:  # pragma: no cover - defensive
            add_check(
                "controller_branch_remote",
                "error",
                "Controller branch does not exist or is not accessible",
                {
                    "full_name": controller_repo,
                    "branch": controller_branch,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        else:
            add_check(
                "controller_branch_remote",
                "ok",
                "Controller branch exists and is accessible",
                {"full_name": controller_repo, "branch": controller_branch},
            )

        try:
            pr_response = await m._github_request(
                "GET",
                f"/repos/{controller_repo}/pulls",
                params={"state": "open", "per_page": 1},
            )
        except Exception as exc:  # pragma: no cover - defensive
            add_check(
                "controller_pr_endpoint",
                "warning",
                "Pull request endpoint is not reachable; PR tools may fail with HTTP errors or timeouts",
                {
                    "full_name": controller_repo,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
        else:
            pr_json = pr_response.get("json")
            open_sample_count = None
            if isinstance(pr_json, list):
                open_sample_count = len(pr_json)
            add_check(
                "controller_pr_endpoint",
                "ok",
                "Pull request endpoint is reachable",
                {
                    "full_name": controller_repo,
                    "sample_open_count": open_sample_count,
                },
            )
    else:
        add_check(
            "controller_remote_checks",
            "warning",
            "Skipped controller repo/branch remote validation because GitHub token is not configured",
            {},
        )

    # Render token checks (presence only; no network calls).
    render_token = _get_optional_render_token()
    if render_token is None:
        add_check(
            "render_token",
            "warning",
            "Render API token is not set; Render tools will fail with authentication errors",
            {"env_vars": list(RENDER_TOKEN_ENV_VARS)},
        )
    else:
        add_check(
            "render_token",
            "ok",
            "Render API token is configured",
            {"length": len(render_token)},
        )

    summary = {
        "ok": sum(1 for c in checks if c["level"] == "ok"),
        "warning": sum(1 for c in checks if c["level"] == "warning"),
        "error": sum(1 for c in checks if c["level"] == "error"),
    }

    return {
        "status": status,
        "summary": summary,
        "checks": checks,
        "config": {
            "controller_repo": controller_repo,
            "controller_branch": controller_branch,
            "github_api_base": m.GITHUB_API_BASE,
        },
    }
