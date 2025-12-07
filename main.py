"""GitHub MCP server exposing connector-friendly tools and workflows.

This module is the entry point for the GitHub Model Context Protocol server
used by ChatGPT connectors. It lists the tools, arguments, and behaviors in a
single place so an assistant can decide how to interact with the server without
being pushed toward a particular working style. See ``docs/WORKFLOWS.md`` and ``docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md``
for optional, non-binding examples of how the tools can fit together.

Controller contract last updated: 2025-03-17.
"""

import asyncio
import base64
import difflib
import json
import jsonschema
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional
from typing import Any, Dict, List, Mapping, Optional

import httpx  # noqa: F401
import github_mcp.tools_workspace as tools_workspace  # noqa: F401
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from github_mcp.config import (  # noqa: F401
    BASE_LOGGER,
    FETCH_FILES_CONCURRENCY,
    GIT_AUTHOR_EMAIL,
    GIT_AUTHOR_NAME,
    GIT_COMMITTER_EMAIL,
    GIT_COMMITTER_NAME,
    GITHUB_API_BASE,
    GITHUB_LOGGER,
    GITHUB_PAT,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    MAX_CONCURRENCY,
    RUN_COMMAND_MAX_CHARS,
    SERVER_START_TIME,
    TOOLS_LOGGER,
    TOOL_STDERR_MAX_CHARS,
    TOOL_STDIO_COMBINED_MAX_CHARS,
    TOOL_STDOUT_MAX_CHARS,
    WORKSPACE_BASE_DIR,
)
from github_mcp.exceptions import (  # noqa: F401
    GitHubAPIError,
    GitHubAuthError,
    GitHubRateLimitError,
    WriteNotAuthorizedError,
)
from github_mcp.github_content import (
    _decode_github_content,
    _get_branch_sha,
    _load_body_from_content_url,
    _perform_github_commit,
    _resolve_file_sha,
    _verify_file_on_branch,
)
from github_mcp import http_clients as _http_clients  # noqa: F401
from github_mcp.http_clients import (  # noqa: F401
    _concurrency_semaphore,
    _external_client_instance,
    _get_github_token,
    _github_client_instance,
    _http_client_external,
    _http_client_github,
)
from github_mcp.metrics import (  # noqa: F401
    _METRICS,
    _metrics_snapshot,
    _record_github_request,
    _record_tool_call,
    _reset_metrics_for_tests,
)
from github_mcp.utils import (
    REPO_DEFAULTS,
    _decode_zipped_job_logs,
    _effective_ref_for_repo,
    _render_visible_whitespace,
    _with_numbered_lines,
    normalize_args,
)
from github_mcp.workspace import (  # noqa: F401
    _apply_patch_to_repo,
    _clone_repo,
    _prepare_temp_virtualenv,
    _run_shell,
    _workspace_path,
)
from github_mcp.tools_workspace import (  # noqa: F401
    commit_workspace,
    commit_workspace_files,
    ensure_workspace_clone,
    run_command,
    run_tests,
)
import github_mcp.server as server  # noqa: F401
from github_mcp.server import (  # noqa: F401
    COMPACT_METADATA_DEFAULT,
    CONTROLLER_CONTRACT_VERSION,
    CONTROLLER_DEFAULT_BRANCH,
    CONTROLLER_REPO,
    _REGISTERED_MCP_TOOLS,
    _ensure_write_allowed,
    _find_registered_tool,
    _github_request,
    _normalize_input_schema,
    _structured_tool_error,
    mcp,
    mcp_tool,
    register_extra_tools_if_available,
)


def __getattr__(name: str):
    if name == "WRITE_ALLOWED":
        return server.WRITE_ALLOWED
    raise AttributeError(name)


# Recalculate write gate on import to honor updated environment variables when
# ``main`` is reloaded in tests.
server.WRITE_ALLOWED = server._env_flag("GITHUB_MCP_AUTO_APPROVE", False)

register_extra_tools_if_available()


@mcp_tool(write_action=False)
def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    """Toggle write-tagged tools on or off for the running server instance.

    Args:
        approved: Set to ``true`` to allow tools marked ``write_action=True`` to
            execute; set to ``false`` to block them. The environment variable
            ``GITHUB_MCP_AUTO_APPROVE`` seeds the initial value, but this tool is
            the runtime override assistants should call when they need to enable
            writes for a session.
    """

    server.WRITE_ALLOWED = bool(approved)
    return {"write_allowed": server.WRITE_ALLOWED}


# ------------------------------------------------------------------------------
# Read-only tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
async def get_server_config() -> Dict[str, Any]:
    """Return a non-sensitive snapshot of connector configuration for assistants.

    Safe to call at the start of a session to understand write gating, HTTP
    timeouts, concurrency limits, and sandbox configuration.
    """

    return {
        "write_allowed": server.WRITE_ALLOWED,
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
            "read_actions": {
                "auto_approved": True,
                "notes": "Read-only tools never require additional approval.",
            },
            "write_actions": {
                "auto_approved": server.WRITE_ALLOWED,
                "requires_authorization": not server.WRITE_ALLOWED,
                "toggle_tool": "authorize_write_actions",
                "notes": (
                    "Most write-tagged tools stay gated until explicitly enabled "
                    "for a session; set GITHUB_MCP_AUTO_APPROVE to trust the "
                    "server by default. Workspace setup and non-mutating commands "
                    "are allowed without flipping the gate unless they install "
                    "dependencies or opt out of the temp venv."
                ),
            },
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
            "github_token_present": bool(
                os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
            ),
        },
    }


@mcp_tool(
    write_action=False,
    description=(
        "Validate and normalize JSON strings before returning them to clients. "
        "Useful when controller prompts require strict JSON responses and the "
        "assistant wants to double-check correctness before replying."
    ),
    tags=["meta", "json", "validation"],
)
def validate_json_string(raw: str) -> Dict[str, Any]:
    """Validate a JSON string and return a canonicalized representation.

    Returns a structured payload indicating whether the JSON parsed
    successfully, an error description when parsing fails, and a
    normalized string the assistant can copy verbatim when it needs to
    emit strict JSON without risking client-side parse errors.
    """

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


@mcp_tool(write_action=False)
async def get_repo_defaults(
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Return default configuration for a GitHub repository.

    If `full_name` is omitted, this uses the controller repository configured
    for this MCP server.
    """

    repo = full_name or CONTROLLER_REPO

    # Ask GitHub for the repository metadata so we can resolve its default
    # branch instead of relying only on local config. Fall back to any
    # configured defaults when the request cannot be made (for example, in
    # hermetic test environments without a GitHub token).
    try:
        data = await _github_request("GET", f"/repos/{repo}")
        payload = data.get("json") or {}
        default_branch = payload.get("default_branch") or CONTROLLER_DEFAULT_BRANCH
    except (GitHubAuthError, GitHubAPIError):
        repo_defaults = REPO_DEFAULTS.get(repo)
        default_branch = (repo_defaults or {}).get("default_branch", CONTROLLER_DEFAULT_BRANCH)

    return {
        "defaults": {
            "full_name": repo,
            "default_branch": default_branch,
        }
    }


@mcp_tool(write_action=False)
async def validate_environment() -> Dict[str, Any]:
    """Validate environment configuration and report common misconfigurations.

    This tool is safe to run at any time. It only inspects process environment
    variables and performs lightweight GitHub API checks for the configured
    controller repository and branch.
    """

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
    raw_token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    token_env_var = (
        "GITHUB_PAT"
        if os.environ.get("GITHUB_PAT") is not None
        else ("GITHUB_TOKEN" if os.environ.get("GITHUB_TOKEN") is not None else None)
    )
    if raw_token is None:
        add_check(
            "github_token",
            "error",
            "GITHUB_PAT or GITHUB_TOKEN is not set",
            {"env_vars": ["GITHUB_PAT", "GITHUB_TOKEN"]},
        )
        token_ok = False
    elif not raw_token.strip():
        add_check(
            "github_token",
            "error",
            "GitHub token environment variable is empty or whitespace",
            {"env_var": token_env_var},
        )
        token_ok = False
    else:
        add_check(
            "github_token",
            "ok",
            "GitHub token is configured",
            {"env_var": token_env_var},
        )
        token_ok = True

    # Controller repo/branch config (string-level)
    controller_repo = CONTROLLER_REPO
    controller_branch = CONTROLLER_DEFAULT_BRANCH
    add_check(
        "controller_repo_config",
        "ok",
        "Controller repository is configured",
        {
            "value": controller_repo,
            "env_var": (
                "GITHUB_MCP_CONTROLLER_REPO"
                if os.environ.get("GITHUB_MCP_CONTROLLER_REPO") is not None
                else None
            ),
        },
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

    # Git identity env vars (presence).
    identity_envs = {
        "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME"),
        "GIT_AUTHOR_EMAIL": os.environ.get("GIT_AUTHOR_EMAIL"),
        "GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME"),
        "GIT_COMMITTER_EMAIL": os.environ.get("GIT_COMMITTER_EMAIL"),
    }
    missing_identity = [name for name, value in identity_envs.items() if not value]
    if missing_identity:
        add_check(
            "git_identity_env",
            "warning",
            "Git identity env vars are not fully configured; defaults may be used for commits",
            {"missing": missing_identity},
        )
    else:
        add_check(
            "git_identity_env",
            "ok",
            "Git identity env vars are configured",
            {},
        )

    # HTTP / concurrency config (always informational; defaults are fine).
    add_check(
        "http_config",
        "ok",
        "HTTP client configuration resolved",
        {
            "github_api_base": GITHUB_API_BASE,
            "timeout": HTTPX_TIMEOUT,
            "max_connections": HTTPX_MAX_CONNECTIONS,
            "max_keepalive": HTTPX_MAX_KEEPALIVE,
        },
    )
    add_check(
        "concurrency_config",
        "ok",
        "Concurrency limits resolved",
        {
            "max_concurrency": MAX_CONCURRENCY,
            "fetch_files_concurrency": FETCH_FILES_CONCURRENCY,
        },
    )

    # Remote validation for controller repo/branch, only if token is usable.
    if token_ok:
        repo_payload: Dict[str, Any] = {}
        try:
            repo_response = await _github_request("GET", f"/repos/{controller_repo}")
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

            push_allowed = (
                permissions.get("push") if isinstance(permissions, dict) else None
            )
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
            await _github_request(
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
            pr_response = await _github_request(
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
            "github_api_base": GITHUB_API_BASE,
        },
    }


@mcp_tool(write_action=True)
async def pr_smoke_test(
    full_name: Optional[str] = None,
    base_branch: Optional[str] = None,
    draft: bool = True,
) -> Dict[str, Any]:
    """Create a trivial branch with a one-line change and open a draft PR.

    This is intended for diagnostics of PR tooling in the live environment.
    """

    defaults = await get_repo_defaults(full_name=full_name)
    defaults_payload = defaults.get("defaults") or {}
    repo = defaults_payload.get("full_name") or full_name or CONTROLLER_REPO
    base = (
        base_branch
        or defaults_payload.get("default_branch")
        or CONTROLLER_DEFAULT_BRANCH
    )

    import uuid

    branch = f"mcp-pr-smoke-{uuid.uuid4().hex[:8]}"

    await ensure_branch(full_name=repo, branch=branch, from_ref=base)

    path = "mcp_pr_smoke_test.txt"
    content = f"MCP PR smoke test branch {branch}.\n"

    await apply_text_update_and_commit(
        full_name=repo,
        path=path,
        updated_content=content,
        branch=branch,
        message=f"MCP PR smoke test on {branch}",
        return_diff=False,
    )

    pr = await create_pull_request(
        full_name=repo,
        title=f"MCP PR smoke test ({branch})",
        head=branch,
        base=base,
        body="Automated MCP PR smoke test created by pr_smoke_test.",
        draft=draft,
    )

    # Normalize the result so smoke-test callers can reliably see whether a PR
    # was actually created and, if so, which URL/number to look at.
    pr_json = pr.get("json") or {}
    if not isinstance(pr_json, dict) or not pr_json.get("number"):
        # Bubble through the structured error shape produced by
        # ``create_pull_request`` so the caller can see status/message details.
        return {
            "status": "error",
            "repository": repo,
            "base": base,
            "branch": branch,
            "raw_response": pr,
        }

    return {
        "status": "ok",
        "repository": repo,
        "base": base,
        "branch": branch,
        "pr_number": pr_json.get("number"),
        "pr_url": pr_json.get("html_url"),
    }


@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    """Return the authenticated token's GitHub rate-limit document."""
    return await _github_request("GET", "/rate_limit")


@mcp_tool(write_action=False)
async def get_user_login() -> Dict[str, Any]:
    """Return the login for the authenticated GitHub user."""

    data = await _github_request("GET", "/user")
    login = None
    if isinstance(data.get("json"), dict):
        login = data["json"].get("login")
    return {
        "status_code": data.get("status_code"),
        "login": login,
        "user": data.get("json"),
    }


@mcp_tool(write_action=False)
async def list_repositories(
    affiliation: Optional[str] = None,
    visibility: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List repositories accessible to the authenticated user."""

    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if affiliation:
        params["affiliation"] = affiliation
    if visibility:
        params["visibility"] = visibility
    return await _github_request("GET", "/user/repos", params=params)


@mcp_tool(write_action=False)
async def list_repositories_by_installation(
    installation_id: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """List repositories accessible via a specific GitHub App installation."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET", f"/user/installations/{installation_id}/repositories", params=params
    )


@mcp_tool(write_action=False)
async def list_recent_issues(
    filter: str = "assigned",
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """Return recent issues the user can access (includes PRs)."""

    params = {"filter": filter, "state": state, "per_page": per_page, "page": page}
    return await _github_request("GET", "/issues", params=params)


@mcp_tool(write_action=False)
async def list_repository_issues(
    full_name: str,
    state: str = "open",
    labels: Optional[List[str]] = None,
    assignee: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List issues for a specific repository (includes PRs)."""

    params: Dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
    if labels:
        params["labels"] = ",".join(labels)
    if assignee is not None:
        params["assignee"] = assignee

    return await _github_request("GET", f"/repos/{full_name}/issues", params=params)


@mcp_tool(write_action=False)
async def fetch_issue(full_name: str, issue_number: int) -> Dict[str, Any]:
    """Fetch a GitHub issue."""

    return await _github_request("GET", f"/repos/{full_name}/issues/{issue_number}")


@mcp_tool(write_action=False)
async def fetch_issue_comments(
    full_name: str, issue_number: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """Fetch comments for a GitHub issue."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/issues/{issue_number}/comments",
        params=params,
    )


@mcp_tool(write_action=False)
async def fetch_pr(full_name: str, pull_number: int) -> Dict[str, Any]:
    """Fetch pull request details."""

    return await _github_request("GET", f"/repos/{full_name}/pulls/{pull_number}")


@mcp_tool(write_action=False)
async def get_pr_info(full_name: str, pull_number: int) -> Dict[str, Any]:
    """Get metadata for a pull request without downloading the diff."""

    data = await fetch_pr(full_name, pull_number)
    pr = data.get("json") or {}
    if isinstance(pr, dict):
        summary = {
            "title": pr.get("title"),
            "state": pr.get("state"),
            "draft": pr.get("draft"),
            "merged": pr.get("merged"),
            "user": pr.get("user", {}).get("login") if isinstance(pr.get("user"), dict) else None,
            "head": pr.get("head", {}).get("ref") if isinstance(pr.get("head"), dict) else None,
            "base": pr.get("base", {}).get("ref") if isinstance(pr.get("base"), dict) else None,
        }
    else:
        summary = None
    return {"status_code": data.get("status_code"), "summary": summary, "pr": pr}


@mcp_tool(write_action=False)
async def fetch_pr_comments(
    full_name: str, pull_number: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """Fetch issue-style comments for a pull request."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET", f"/repos/{full_name}/issues/{pull_number}/comments", params=params
    )


@mcp_tool(write_action=False)
async def get_pr_diff(full_name: str, pull_number: int) -> Dict[str, Any]:
    """Fetch the unified diff for a pull request."""

    return await _github_request(
        "GET",
        f"/repos/{full_name}/pulls/{pull_number}",
        headers={"Accept": "application/vnd.github.v3.diff"},
        expect_json=False,
    )


@mcp_tool(write_action=False)
async def fetch_pr_patch(full_name: str, pull_number: int) -> Dict[str, Any]:
    """Fetch the patch for a GitHub pull request."""

    return await _github_request(
        "GET",
        f"/repos/{full_name}/pulls/{pull_number}",
        headers={"Accept": "application/vnd.github.v3.patch"},
        expect_json=False,
    )


@mcp_tool(write_action=False)
async def list_pr_changed_filenames(
    full_name: str, pull_number: int, per_page: int = 100, page: int = 1
) -> Dict[str, Any]:
    """List files changed in a pull request."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET", f"/repos/{full_name}/pulls/{pull_number}/files", params=params
    )


@mcp_tool(write_action=False)
async def get_commit_combined_status(full_name: str, ref: str) -> Dict[str, Any]:
    """Get combined status for a commit or ref."""

    return await _github_request("GET", f"/repos/{full_name}/commits/{ref}/status")


@mcp_tool(write_action=False)
async def get_issue_comment_reactions(
    full_name: str, comment_id: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """Fetch reactions for an issue comment."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/issues/comments/{comment_id}/reactions",
        params=params,
        headers={"Accept": "application/vnd.github.squirrel-girl+json"},
    )


@mcp_tool(write_action=False)
async def get_pr_reactions(
    full_name: str, pull_number: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """Fetch reactions for a GitHub pull request."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/issues/{pull_number}/reactions",
        params=params,
        headers={"Accept": "application/vnd.github.squirrel-girl+json"},
    )


@mcp_tool(write_action=False)
async def get_pr_review_comment_reactions(
    full_name: str, comment_id: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    """Fetch reactions for a pull request review comment."""

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/pulls/comments/{comment_id}/reactions",
        params=params,
        headers={"Accept": "application/vnd.github.squirrel-girl+json"},
    )


@mcp_tool(write_action=False)
def list_write_tools() -> Dict[str, Any]:
    """Describe write-capable tools exposed by this server.

    This is intended for assistants to discover what they can do safely without
    reading the entire main.py.
    """

    tools = [
        {
            "name": "authorize_write_actions",
            "category": "control",
            "description": "Enable or disable write tools within this MCP session.",
            "notes": "Call with approved=true before using any write tools.",
        },
        {
            "name": "create_branch",
            "category": "branch",
            "description": "Create a new branch from a base ref.",
            "notes": "Prefer ensure_branch unless you know the branch does not exist.",
        },
        {
            "name": "ensure_branch",
            "category": "branch",
            "description": "Ensure a branch exists, creating it from a base ref if needed.",
            "notes": "Safe default for preparing branches before commits or PRs.",
        },
        {
            "name": "update_file_and_open_pr",
            "category": "pr",
            "description": "Fast path: commit one file and open a PR without cloning.",
            "notes": "Use for tiny fixes like lint nits or typo corrections.",
        },
        {
            "name": "create_pull_request",
            "category": "pr",
            "description": "Open a GitHub pull request between two branches.",
            "notes": "Usually called indirectly by higher-level tools.",
        },
        {
            "name": "update_files_and_open_pr",
            "category": "pr",
            "description": "Commit multiple files and open a PR in one call.",
            "notes": "Use primarily for docs and multi-file updates.",
        },
        {
            "name": "ensure_workspace_clone",
            "category": "workspace",
            "description": "Ensure a persistent workspace exists for a repo/ref.",
            "notes": "Clones if missing and can optionally reset to the remote ref; now allowed without toggling write approval so assistants can set up quickly.",
        },
        {
            "name": "run_command",
            "category": "workspace",
            "description": "Run an arbitrary shell command in a persistent workspace clone.",
            "notes": "Shares the same persistent workspace used by commit tools so edits survive across calls; set mutating=true (or installing_dependencies=true/use_temp_venv=false) when a command will modify files or server state so gating applies only to those cases.",
        },
        {
            "name": "commit_workspace",
            "category": "workspace",
            "description": "Commit and optionally push changes from the persistent workspace.",
            "notes": "Stages changes, commits with a provided message, and can push to the effective branch.",
        },
        {
            "name": "commit_workspace_files",
            "category": "workspace",
            "description": "Commit a specific list of files from the persistent workspace.",
            "notes": "Use to avoid staging temporary artifacts while still pushing changes to the branch.",
        },
        {
            "name": "run_tests",
            "category": "workspace",
            "description": "Run tests (default: pytest) inside the persistent workspace clone.",
            "notes": "Preferred way to run tests; shares the persistent workspace with run_command and commit helpers. Mark mutating=true only when the test command will edit files so read-only runs stay ungated.",
        },
        {
            "name": "trigger_workflow_dispatch",
            "category": "workflow",
            "description": "Trigger a GitHub Actions workflow via workflow_dispatch.",
            "notes": "Use only when Joey explicitly asks to run a workflow.",
        },
        {
            "name": "trigger_and_wait_for_workflow",
            "category": "workflow",
            "description": "Trigger a workflow and poll until completion or timeout.",
            "notes": "Summarize the run result in your response.",
        },
        {
            "name": "create_issue",
            "category": "issue",
            "description": "Open a GitHub issue with optional body, labels, and assignees.",
            "notes": "Use to capture new work items or questions.",
        },
        {
            "name": "update_issue",
            "category": "issue",
            "description": "Update fields on an existing GitHub issue.",
            "notes": "Adjust scope, status, or ownership directly in the issue.",
        },
        {
            "name": "comment_on_issue",
            "category": "issue",
            "description": "Post a comment on an existing GitHub issue.",
            "notes": "Log progress updates and decisions.",
        },
        {
            "name": "merge_pull_request",
            "category": "pr",
            "description": "Merge an existing PR using the chosen method.",
            "notes": "Assistants should only merge when Joey explicitly requests it.",
        },
        {
            "name": "close_pull_request",
            "category": "pr",
            "description": "Close an existing PR without merging.",
            "notes": "Only when Joey asks to close a PR.",
        },
        {
            "name": "comment_on_pull_request",
            "category": "pr",
            "description": "Post a comment on an existing PR.",
            "notes": "Use for status, summaries, or test results if Joey likes that pattern.",
        },
    ]

    return {"tools": tools}


@mcp_tool(write_action=False)
def controller_contract(compact: Optional[bool] = None) -> Dict[str, Any]:
    """Return the controller/assistant contract in a structured format.

    This payload is meant to reduce misunderstandings between controller
    prompts, assistants, and the MCP server. Controllers can surface it to
    ChatGPT to remind the assistant which workflows are expected and how writes
    are gated.

    When ``compact`` is ``True`` (or when ``GITHUB_MCP_COMPACT_METADATA=1`` is
    set), the response is shortened to reduce token usage while keeping counts
    and summaries available.
    """

    compact_mode = COMPACT_METADATA_DEFAULT if compact is None else compact

    assistant_expectations = [
        "On the first tool use of a session (or after context loss), run the startup checklist: get_server_config, controller_contract with compact=true, list_all_actions with include_parameters=true, and describe_tool plus validate_tool_args before you invoke unfamiliar or write tools; cache these results instead of guessing schemas.",
        "Use run_command and run_tests as the default execution paths for inspecting repos, installing dependencies, running checks, and driving local workflows; do not assume packages are installed in the MCP server process.",
        "Keep run_command and run_tests visible in normal workflows instead of avoiding them; they are part of the expected toolchain.",
        "Treat run_command as your keyboard on a dedicated development machine: run project-specific or shell-level commands (including git, editors, linters, formatters, build scripts, migrations, and one-off diagnostics) there instead of inventing inline workarounds.",
        "Discourage token-heavy inline calls for data gathering or editing; prefer targeted run_command queries, slices, and diffs so outputs stay concise.",
        "Approach tasks like a real developer: gather context from relevant files, usages, and tests before editing, and reference concrete modules, identifiers, and line numbers when summarizing findings or planning changes.",
        "Remember that only the assistant drives tool calls: do not ask humans to type commands, add blank lines, or re-run failed steps manually. Use diff-based tools and workspace helpers to handle quoting, newlines, and retries yourself.",
        "Default to the branch-diff-test-PR flow: create or ensure a feature branch before edits, apply diffs with patch helpers instead of ad-hoc inline scripts, run tests or repo-native checks on that branch, and open a pull request with a concise summary when work is done.",
        "Run repo-defined linters and formatters (especially autofix variants) before proposing commits or PRs so style or syntax issues are caught early instead of left for humans to debug.",
        "Whenever you change code or behavior, create or update tests so that run_tests on the active branch actually verifies the new behavior; do not treat tests as optional.",
        "When asked to open a pull request after finishing work, target the main branch (or the configured default branch) unless the user explicitly specifies a different base.",
        "Work on feature branches and avoid writing to main for the controller repo unless explicitly told otherwise.",
        "Keep GitHub state changes gated behind authorize_write_actions, but treat workspace setup, discovery, and non-mutating commands as auto-approved so flow is fast by default.",
        "Call run_command with installing_dependencies=true (or use_temp_venv=false) when a command needs to install or mutate server-level state so gating can apply to that narrower slice of work.",
        "Summarize what changed and which tools ran so humans can audit actions easily.",
        "Return strict, valid JSON by validating payloads with validate_json_string before emitting them to clients.",
        "Treat validate_tool_args as the default pre-flight for new or write tools; if validation fails, stop and repair the payload based on the published schema instead of retrying blindly.",
        "When you generate non-trivial scripts, commands, or configuration (for example Python snippets, shell scripts, or large JSON payloads), run appropriate workspace tools via run_command to validate them (such as python -m py_compile for Python, bash -n or shellcheck for shell, validate_json_string and validate_tool_args for JSON and tool calls) before relying on them or committing.",
        "When updating code or docs, remove or rewrite outdated or conflicting content so the final state has no duplicates or obsolete paths.",
        "Whenever documentation in this controller repo has been updated and merged into the default branch, re-read the updated documents through the Adaptiv controller tools (for example get_file_contents, fetch_files, or list_repository_tree) and treat them as the new source of truth for the project; a merged PR on the default branch means the human has already reviewed and accepted the changes.",
        "Work from natural-language goals without demanding long lists of CLI commands; ask concise clarifying questions instead of offloading planning to humans.",
        "Verify outputs and state before repeating actions so runs do not get stuck in loops; report blockers clearly.",
        "Use get_file_slice and diff helpers for large files when they make changes easier to see or safer to apply; for small, clear edits it is fine to update full files as long as the change stays focused and easy to review.",
        "When you need line references for edits or citations, call get_file_with_line_numbers instead of hand-numbering snippets; pair it with get_file_slice so your patches and summaries point at exact lines without rewriting the whole file.",
        "Treat routine multi-line edits as normal; rely on diff-based tools like apply_text_update_and_commit, apply_patch_and_commit, or update_file_sections_and_commit instead of calling them tricky or offloading them to humans.",
        "Follow each tool's declared parameter schema exactly. Do not invent arguments such as full_name, owner, or repo unless they are explicitly defined in the tool signature.",
        "Build tool arguments with literal JSON objects and real newlines: do not wrap payloads in extra quotes, avoid sprinkling \\n escapes inside values unless the tool expects them, escape double quotes only inside string values, and run validate_tool_args or validate_json_string when uncertain so controllers see clean, copyable examples instead of over-escaped blobs.",
        "When you need to search within the controller repo, prefer repo-scoped helpers or include an explicit repo:Proofgate-Revocations/chatgpt-mcp-github qualifier in search queries. Do not use unqualified global GitHub search for routine controller work.",
        "Treat unscoped global code searches as exceptional: only use them when the user explicitly asks for cross-repo or ecosystem-wide context, and never to inspect or navigate this controller repo.",
        "If a tool call returns a schema or validation error (for example an unexpected parameter), stop and re-read the tool definition via list_all_actions(include_parameters=true). Fix the arguments to match the schema instead of guessing or retrying with made-up parameters.",
        "Do not switch between different search interfaces mid-task without reason. Once you have chosen a repo-scoped search strategy for a task in this controller repo, stick to it unless the user clearly requests a change.",
        "When the conversation resets or the context window shrinks, rehydrate before acting: rerun controller_contract and get_server_config, reopen the relevant files with get_file_contents/get_file_slice or fetch_files, and use run_command or search tools (with repo scoping) to rebuild the working set before proposing edits.",
        "Treat these expectations as guardrails rather than hard locks; do not get stuck over choices like patch versus full-file updates or which search helper to use—pick a reasonable option, explain it briefly, and keep the work moving.",
    ]

    controller_prompt_expectations = [
        "Adopt the official system prompt from docs/CONTROLLER_PROMPT_V1.md (or its current version) so assistants internalize their role, startup checklist, and no-offloading stance before issuing any tool calls.",
        "Remind assistants to respect branch defaults, keep writes gated until authorized, and use the persistent workspace tools (run_command, run_tests, commit_workspace, commit_workspace_files) as the standard execution surface.",
        "Keep safety, truncation, and large-file guidance visible so the controller prompt steers assistants toward slice-and-diff workflows instead of large payload retries.",
        "Coach assistants to anchor their reasoning in concrete repo context: point them to the files, functions, and tests they should inspect, and ask for summaries with paths and line references instead of vague statements.",
        "Include a quick rehydration playbook for assistants to follow after disconnects or blank contexts: rerun controller_contract, refresh server and branch info, and reopen the specific files or slices tied to the task before resuming edits.",
    ]

    server_expectations = [
        "Reject write tools when WRITE_ALLOWED is false and surface clear errors for controllers to relay.",
        "Default to the configured controller branch when refs are missing for the controller repo to reduce accidental writes to main.",
        "Normalize PR base branches to the configured controller default when callers omit a base or use main so controllers reliably open PRs against the intended target.",
        "Expose minimal health and metrics data so controllers can debug without extra API calls.",
    ]

    controller_prompt_prompts = [
        "Call get_server_config early to learn write_allowed, HTTP limits, and controller defaults.",
        "Point assistants to docs/start_session.md so they actually run the startup sequence (get_server_config, controller_contract with compact=true, list_all_actions with include_parameters=true, describe_tool, validate_tool_args) before guessing any schema or issuing writes.",
        "Encourage use of list_write_tools, validate_tool_args, and validate_environment so the assistant knows available tools and common pitfalls.",
        "Remind assistants that run_command and run_tests are allowed by default and should be part of normal execution workflows when available.",
        "Only gate commands that install dependencies or mutate server state; discovery and workspace setup should flow without extra approvals.",
        "Push assistants to run repo-native linters and formatters early (especially autofixers) so trivial syntax or style errors are resolved before code review.",
        "Encourage assistants to add or adjust tests alongside code changes and to run run_tests on the relevant feature branch before opening PRs.",
        "Steer assistants toward update_files_and_open_pr or apply_patch_and_commit instead of low-level Git operations.",
        "Nudge assistants toward large-file helpers like get_file_slice, build_section_based_diff, and validate_json_string to avoid retries and token blowups.",
        "Remind assistants that search tools have strict schemas; they must use only the parameters documented in list_all_actions(include_parameters=true) and must not invent arguments like full_name unless explicitly supported.",
        "Encourage assistants to treat repo-scoped search as the default for this controller repo by using dedicated repo helpers or including repo:Proofgate-Revocations/chatgpt-mcp-github in search queries.",
        "Discourage unqualified global GitHub searches for normal controller tasks; global search should only be used when the user explicitly asks for cross-repo or ecosystem-wide context.",
        "When a search or other tool call fails with a validation or schema error, instruct assistants to correct the call using the tool's declared parameters instead of repeatedly guessing new arguments.",
        "Model the branch-diff-test-PR flow in the prompt so assistants remember to create feature branches, use diff-based edit tools, run tests, and open PRs instead of offloading work to humans.",
    ]

    server_prompts = [
        "Reject write tools when WRITE_ALLOWED is false and surface clear errors for controllers to relay.",
        "Default to the configured controller branch when refs are missing for the controller repo to reduce accidental writes to main.",
        "Expose minimal health and metrics data so controllers can debug without extra API calls.",
    ]

    editing_preferences = {
        "summary": (
            "Use diff-oriented tools for file changes and treat run_command as "
            "your interactive terminal for quick checks. Avoid token-heavy "
            "inline payloads or heredocs when a focused command, slice, or diff "
            "keeps context tight."
        ),
        "recommended_tools": [
            "build_unified_diff",
            "build_section_based_diff",
            "apply_text_update_and_commit",
            "apply_patch_and_commit",
            "update_files_and_open_pr",
        ],
        "anti_patterns": [
            "Embedding large Python or shell scripts in run_command.command to " "edit files.",
        ],
    }

    tooling = {
        "discovery": [
            "get_server_config",
            "list_write_tools",
            "validate_tool_args",
            "validate_environment",
        ],
        "safety": [
            "authorize_write_actions",
            "ensure_branch",
            "apply_patch_and_commit",
            "apply_text_update_and_commit",
            "update_files_and_open_pr",
        ],
        "execution": ["run_command", "run_tests", "commit_workspace", "commit_workspace_files"],
        "diffs": ["build_unified_diff", "build_section_based_diff"],
        "large_files": [
            "get_file_slice",
            "build_section_based_diff",
            "build_unified_diff_from_strings",
            "validate_json_string",
        ],
        "issues": ["create_issue", "update_issue", "comment_on_issue", "open_issue_context"],
        "branches": ["compare_refs", "get_branch_summary"],
    }

    guardrails = [
        "Always verify branch and ref inputs when using git-aware tools; prefer explicit branch names or commit SHAs over defaults when modifying code or opening pull requests.",
        "Do not bypass write gating or auto-approval flows; if a write is denied, stop and surface the reason instead of attempting alternate write paths.",
        "When content drift is detected between your working copy and GitHub, re-fetch or re-clone before applying large changes so patches are computed against the current remote state.",
        "Prefer slice-and-diff workflows for large files or risky edits; avoid overwriting entire files when a small, well-scoped patch is sufficient.",
        "Pause and summarize after repeated failures with the same tool; show recent inputs and outputs and propose a revised plan instead of blindly retrying.",
        "When responding with tool calls for this controller repo, begin by listing the concrete actions you will take in that turn so humans can confirm the sequence before you execute them.",
        "For this controller repo, once you have created or ensured a feature branch for a task, treat that branch as the single source of truth and do not treat main as the reference while you are fixing issues that exist on main; rely on the feature branch plus its tests and linters.",
        "After you commit changes from the persistent workspace, re-clone the same branch with ensure_workspace_clone(reset=true) before running run_tests or repo-defined lint suites so verification runs in a fresh workspace that matches GitHub state.",
        "Treat validate_environment and other deployment checks as dependent on Joey merging and restarting the service; use them sparingly, do not loop on them, and never claim you merged or restarted anything yourself.",
    ]

    payload: Dict[str, Any] = {
        "version": CONTROLLER_CONTRACT_VERSION,
        "summary": "Contract describing how controllers, assistants, and this GitHub MCP server work together.",
        "controller": {
            "repo": CONTROLLER_REPO,
            "default_branch": CONTROLLER_DEFAULT_BRANCH,
            "write_allowed_default": server.WRITE_ALLOWED,
        },
        "expectations": {
            "assistant": assistant_expectations,
            "controller_prompt": controller_prompt_expectations,
            "server": server_expectations,
        },
        "prompts": {
            "controller_prompt": controller_prompt_prompts,
            "server": server_prompts,
        },
        "editing_preferences": editing_preferences,
        "tooling": tooling,
        "guardrails": guardrails,
    }

    if compact_mode:
        payload["compact"] = True
        payload["expectations"] = {
            "assistant_count": len(assistant_expectations),
            "controller_prompt_count": len(controller_prompt_expectations),
            "server_count": len(server_expectations),
            "note": "Set compact=false to receive the full expectation text.",
        }
        payload["prompts"] = {
            "controller_prompt_count": len(controller_prompt_prompts),
            "server_count": len(server_prompts),
            "note": "Set compact=false to receive the full prompt guidance.",
        }
        payload["guardrails"] = {
            "count": len(guardrails),
            "examples": guardrails[:2],
        }

    return payload


@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> Dict[str, Any]:
    """Look up repository metadata (topics, default branch, permissions)."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    return await _github_request("GET", f"/repos/{full_name}")


@mcp_tool(write_action=False)
async def list_branches(
    full_name: str,
    per_page: int = 100,
    page: int = 1,
) -> Dict[str, Any]:
    """Enumerate branches for a repository with GitHub-style pagination."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    params = {"per_page": per_page, "page": page}
    return await _github_request("GET", f"/repos/{full_name}/branches", params=params)


@mcp_tool(write_action=True)
async def move_file(
    full_name: str,
    from_path: str,
    to_path: str,
    branch: str = "main",
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Move or rename a file within a repository on a single branch.

    This helper reads the source path at the given branch, writes its contents
    to the destination path, and then deletes the original path using the same
    commit/contents APIs as other file helpers.
    """

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    effective_branch = _effective_ref_for_repo(full_name, branch)

    _ensure_write_allowed(
        f"move_file from {from_path} to {to_path} in {full_name}@{effective_branch}",
        target_ref=effective_branch,
    )

    if from_path == to_path:
        raise ValueError("from_path and to_path must be different")

    # Read the source file text first.
    source = await _decode_github_content(full_name, from_path, effective_branch)
    source_text = source.get("text")
    if source_text is None:
        raise GitHubAPIError("Source file contents missing or undecodable")

    commit_message = message or f"Move {from_path} to {to_path}"

    # 1) Write the destination file with the source contents.
    write_result = await apply_text_update_and_commit(
        full_name=full_name,
        path=to_path,
        updated_content=source_text,
        branch=effective_branch,
        message=commit_message + " (add new path)",
        return_diff=False,
    )

    # 2) Delete the original path now that the destination exists.
    delete_body = {
        "message": commit_message + " (remove old path)",
        "branch": effective_branch,
    }
    try:
        delete_body["sha"] = await _resolve_file_sha(full_name, from_path, effective_branch)
    except GitHubAPIError as exc:
        msg = str(exc)
        if "404" in msg and "/contents/" in msg:
            delete_result = {"status": "noop", "reason": "source path missing"}
        else:
            raise
    else:
        delete_result = await _github_request(
            "DELETE",
            f"/repos/{full_name}/contents/{from_path}",
            json=delete_body,
        )

    return {
        "status": "moved",
        "full_name": full_name,
        "branch": effective_branch,
        "from_path": from_path,
        "to_path": to_path,
        "write_result": write_result,
        "delete_result": delete_result,
    }


@mcp_tool(write_action=False)
async def get_file_contents(
    full_name: str,
    path: str,
    ref: str = "main",
) -> Dict[str, Any]:
    """Fetch a single file from GitHub and decode base64 to UTF-8 text."""
    return await _decode_github_content(full_name, path, ref)


@mcp_tool(write_action=False)
async def fetch_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
) -> Dict[str, Any]:
    """Fetch multiple files concurrently with per-file error isolation."""

    results: Dict[str, Any] = {}
    sem = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def _fetch_single(p: str) -> None:
        async with sem:
            try:
                decoded = await _decode_github_content(full_name, p, ref)
                results[p] = decoded
            except Exception as e:
                # Use a consistent error envelope so controllers can rely on structure.
                results[p] = _structured_tool_error(
                    str(e),
                    context="fetch_files",
                    path=p,
                )

    await asyncio.gather(*[_fetch_single(p) for p in paths])
    return {"files": results}


@mcp_tool(write_action=False)
async def build_unified_diff(
    full_name: str,
    path: str,
    new_content: str,
    ref: str = "main",
    context_lines: int = 3,
    show_whitespace: bool = False,
) -> Dict[str, Any]:
    """Generate a unified diff for a file against proposed new content.

    Args:
        full_name: ``owner/repo`` string.
        path: Repository-relative file path to diff.
        new_content: Proposed replacement content for the file.
        ref: Branch, tag, or commit SHA to compare against (default ``main``).
        context_lines: Number of unchanged context lines to include in the diff
            (default ``3``).
        show_whitespace: When ``True``, include a whitespace-visualized version
            of the base, proposed, and diff outputs so assistants can see tabs
            and trailing spaces that UI layers might hide.

    Raises:
        ValueError: If ``context_lines`` is negative.
        GitHubAPIError: If the base file cannot be fetched (for example missing
            file, ref, or permissions).
    """

    if context_lines < 0:
        raise ValueError("context_lines must be non-negative")

    base = await _decode_github_content(full_name, path, ref)
    base_text = base.get("text", "")

    diff_lines = difflib.unified_diff(
        base_text.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context_lines,
    )
    diff_text = "".join(diff_lines)

    response: Dict[str, Any] = {
        "path": path,
        "ref": ref,
        "context_lines": context_lines,
        "base": {
            "text": base_text,
            "numbered_lines": base.get("numbered_lines"),
        },
        "proposed": {
            "text": new_content,
            "numbered_lines": _with_numbered_lines(new_content),
        },
        "diff": diff_text,
    }

    if show_whitespace:
        response["visible_whitespace"] = {
            "base": _render_visible_whitespace(base_text),
            "proposed": _render_visible_whitespace(new_content),
            "diff": _render_visible_whitespace(diff_text),
        }

    return response


@mcp_tool(write_action=False)
async def list_repository_tree(
    full_name: str,
    ref: str = "main",
    path_prefix: Optional[str] = None,
    recursive: bool = True,
    max_entries: int = 1000,
    include_blobs: bool = True,
    include_trees: bool = True,
) -> Dict[str, Any]:
    """List files and folders in a repository tree with optional filtering.

    Args:
        full_name: ``owner/repo`` string.
        ref: Branch, tag, or commit SHA to inspect (default ``main``).
        path_prefix: If set, only include entries whose paths start with this
            prefix (useful for zooming into subdirectories without fetching a
            huge response).
        recursive: Whether to request a recursive tree (default ``True``).
        max_entries: Maximum number of entries to return (default ``1000``).
        include_blobs: Include files in the listing (default ``True``).
        include_trees: Include directories in the listing (default ``True``).

    The GitHub Trees API caps responses at 100,000 entries server side. This
    tool applies an additional ``max_entries`` limit so assistants get a fast,
    bounded listing. When ``truncated`` is true in the response, narrow the
    ``path_prefix`` and call again.
    """

    if max_entries <= 0:
        raise ValueError("max_entries must be a positive integer")

    params = {"recursive": 1 if recursive else 0}
    data = await _github_request("GET", f"/repos/{full_name}/git/trees/{ref}", params=params)

    payload = data.get("json") or {}
    tree = payload.get("tree")
    if not isinstance(tree, list):
        raise GitHubAPIError("Unexpected tree response from GitHub")

    allowed_types = set()
    if include_blobs:
        allowed_types.add("blob")
    if include_trees:
        allowed_types.add("tree")
    if not allowed_types:
        return {
            "entries": [],
            "entry_count": 0,
            "truncated": False,
            "message": "Both blobs and trees were excluded; nothing to return.",
        }

    normalized_prefix = path_prefix.lstrip("/") if path_prefix else None

    filtered_entries: List[Dict[str, Any]] = []
    for entry in tree:
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type")
        if entry_type not in allowed_types:
            continue
        path = entry.get("path")
        if not isinstance(path, str):
            continue
        if normalized_prefix and not path.startswith(normalized_prefix):
            continue

        filtered_entries.append(
            {
                "path": path,
                "type": entry_type,
                "mode": entry.get("mode"),
                "size": entry.get("size"),
                "sha": entry.get("sha"),
            }
        )

    truncated = len(filtered_entries) > max_entries
    return {
        "ref": payload.get("sha") or ref,
        "entry_count": len(filtered_entries),
        "truncated": truncated,
        "entries": filtered_entries[:max_entries],
    }


@mcp_tool(write_action=False)
async def graphql_query(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a GitHub GraphQL query using the shared HTTP client and logging wrapper."""

    payload = {"query": query, "variables": variables or {}}
    result = await _github_request(
        "POST",
        "/graphql",
        json_body=payload,
    )
    return result.get("json")


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch an arbitrary HTTP/HTTPS URL via the shared external client."""

    client = _external_client_instance()
    async with _concurrency_semaphore:
        try:
            resp = await client.get(url)
        except Exception as e:
            return _structured_tool_error(
                str(e),
                context="fetch_url",
                path=url,
            )

    return {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "content": resp.text,
    }


@mcp_tool(write_action=False)
async def search(
    query: str,
    search_type: str = "code",
    per_page: int = 30,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform GitHub search queries (code, repos, issues, commits, or users)."""

    allowed_types = {"code", "repositories", "issues", "commits", "users"}
    if search_type not in allowed_types:
        raise ValueError(f"search_type must be one of {sorted(allowed_types)}")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    params: Dict[str, Any] = {"q": query, "per_page": per_page, "page": page}
    if sort:
        params["sort"] = sort
    if order is not None:
        allowed_order = {"asc", "desc"}
        if order not in allowed_order:
            raise ValueError("order must be 'asc' or 'desc'")
        params["order"] = order
    return await _github_request("GET", f"/search/{search_type}", params=params)


@mcp_tool(write_action=False)
async def download_user_content(content_url: str) -> Dict[str, Any]:
    """Download user-provided content (sandbox/local/http) with base64 encoding."""

    body_bytes = await _load_body_from_content_url(content_url, context="download_user_content")
    text: Optional[str]
    try:
        text = body_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = None

    return {
        "size": len(body_bytes),
        "base64": base64.b64encode(body_bytes).decode("ascii"),
        "text": text,
        "numbered_lines": _with_numbered_lines(text) if text is not None else None,
    }


# ------------------------------------------------------------------------------
# GitHub Actions tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
async def list_workflow_runs(
    full_name: str,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    event: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List recent GitHub Actions workflow runs with optional filters."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    if event:
        params["event"] = event
    return await _github_request(
        "GET",
        f"/repos/{full_name}/actions/runs",
        params=params,
    )


@mcp_tool(write_action=False)
async def list_recent_failures(
    full_name: str,
    branch: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """List recent failed or cancelled GitHub Actions workflow runs.

    This helper composes ``list_workflow_runs`` and filters to runs whose
    conclusion indicates a non-successful outcome (for example failure,
    cancelled, or timed out). It is intended as a navigation helper for CI
    debugging flows.
    """

    if limit <= 0:
        raise ValueError("limit must be > 0")

    # Fetch a bounded page of recent runs; callers can tune ``limit`` but
    # results are further filtered to non-successful conclusions.
    per_page = min(max(limit, 10), 50)

    runs_resp = await list_workflow_runs(
        full_name=full_name,
        branch=branch,
        per_page=per_page,
        page=1,
    )

    runs_json = runs_resp.get("json") or {}
    raw_runs = runs_json.get("workflow_runs", []) if isinstance(runs_json, dict) else []

    failure_conclusions = {
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "startup_failure",
    }

    failures: List[Dict[str, Any]] = []
    for run in raw_runs:
        status = run.get("status")
        conclusion = run.get("conclusion")

        if conclusion in failure_conclusions:
            include = True
        elif status == "completed" and conclusion not in (None, "success", "neutral", "skipped"):
            include = True
        else:
            include = False

        if not include:
            continue

        failures.append(
            {
                "id": run.get("id"),
                "name": run.get("name"),
                "event": run.get("event"),
                "status": status,
                "conclusion": conclusion,
                "head_branch": run.get("head_branch"),
                "head_sha": run.get("head_sha"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
                "html_url": run.get("html_url"),
            }
        )

        if len(failures) >= limit:
            break

    return {
        "full_name": full_name,
        "branch": branch,
        "limit": limit,
        "runs": failures,
    }


@mcp_tool(write_action=False)
def list_all_actions(
    include_parameters: bool = False, compact: Optional[bool] = None
) -> Dict[str, Any]:
    """Enumerate every available MCP tool with read/write metadata.

    This helper exposes a structured catalog of all tools so assistants can see
    the full command surface without reading this file. It is intentionally
    read-only and can therefore be called before write approval is granted.

    Args:
        include_parameters: When ``True``, include the serialized input schema
            for each tool to clarify argument names and types.
        compact: When ``True`` (or when ``GITHUB_MCP_COMPACT_METADATA=1`` is
            set), shorten descriptions and omit tag metadata to reduce token
            usage.
    """

    compact_mode = COMPACT_METADATA_DEFAULT if compact is None else compact

    tools: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    for tool, func in _REGISTERED_MCP_TOOLS:
        name = getattr(tool, "name", None) or getattr(func, "__name__", None)
        if not name:
            continue
        name_str = str(name)
        if name_str in seen_names:
            continue
        seen_names.add(name_str)

        meta = getattr(tool, "meta", {}) or {}
        annotations = getattr(tool, "annotations", None)

        description = getattr(tool, "description", None) or (func.__doc__ or "")
        description = description.strip()

        if compact_mode and description:
            compact_description = description.splitlines()[0].strip() or description
            max_length = 200
            if len(compact_description) > max_length:
                compact_description = f"{compact_description[:max_length-3].rstrip()}..."
            description = compact_description

        tool_info: Dict[str, Any] = {
            "name": name_str,
            "write_action": bool(meta.get("write_action")),
            "auto_approved": bool(meta.get("auto_approved")),
            "read_only_hint": getattr(annotations, "readOnlyHint", None),
        }

        if description:
            tool_info["description"] = description

        if not compact_mode:
            tool_info["tags"] = sorted(list(getattr(tool, "tags", []) or []))

        if include_parameters:
            # Surface a best-effort JSON schema for each tool so callers can
            # reason about argument names and types. When the underlying MCP
            # tool does not expose an explicit inputSchema, we still return a
            # minimal object schema instead of ``null`` so downstream
            # assistants can treat the presence of input_schema as a stable
            # contract.
            schema = _normalize_input_schema(tool)
            if schema is None:
                schema = {"type": "object", "properties": {}}
            tool_info["input_schema"] = schema

        tools.append(tool_info)

    tools.sort(key=lambda entry: entry["name"])

    return {
        "write_actions_enabled": server.WRITE_ALLOWED,
        "compact": compact_mode,
        "tools": tools,
    }


@mcp_tool(
    write_action=False,
    description=(
        "Return metadata and optional schema for a single tool. "
        "Prefer this over manually scanning list_all_actions in long sessions."
    ),
)
async def describe_tool(name: str, include_parameters: bool = True) -> Dict[str, Any]:
    """Inspect one registered MCP tool by name.

    This is a convenience wrapper around list_all_actions: it lets callers
    inspect one tool by name without scanning the entire tool catalog.

    Args:
        name: The MCP tool name (for example, \"update_files_and_open_pr\").
        include_parameters: When True, include the serialized input schema for
            this tool (equivalent to list_all_actions(include_parameters=True)).
    """

    catalog = list_all_actions(include_parameters=include_parameters, compact=False)
    for entry in catalog.get("tools", []):
        if entry.get("name") == name:
            return entry

    raise ValueError(f"Unknown tool name: {name}")


@mcp_tool(write_action=False)
async def validate_tool_args(
    tool_name: str, args: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Validate a candidate payload against a tool's input schema without running it."""

    found = _find_registered_tool(tool_name)
    if found is None:
        available = sorted(
            set(
                getattr(tool, "name", None) or getattr(func, "__name__", None)
                for tool, func in _REGISTERED_MCP_TOOLS
                if getattr(tool, "name", None) or getattr(func, "__name__", None)
            )
        )
        raise ValueError(f"Unknown tool {tool_name!r}. Available tools: {', '.join(available)}")

    tool, _ = found
    schema = _normalize_input_schema(tool)

    # For some tools we know the expected argument contract even when the MCP
    # layer does not expose a concrete inputSchema. In those cases we build a
    # small JSON schema by hand so callers can preflight their payloads.
    if schema is None and tool_name == "compare_refs":
        schema = {
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "base": {"type": "string"},
                "head": {"type": "string"},
            },
            "required": ["full_name", "base", "head"],
            "additionalProperties": True,
        }

    normalized_args = normalize_args(args or {})

    if schema is None:
        return {
            "tool": tool_name,
            "valid": True,
            "warnings": [
                "No input schema available for this tool; nothing to validate.",
            ],
            "schema": None,
            "errors": [],
        }

    validator = jsonschema.Draft7Validator(schema)
    errors = [
        {
            "message": error.message,
            "path": list(error.absolute_path),
            "validator": error.validator,
            "validator_value": error.validator_value,
        }
        for error in sorted(validator.iter_errors(normalized_args), key=str)
    ]

    return {
        "tool": tool_name,
        "valid": len(errors) == 0,
        "errors": errors,
        "schema": schema,
    }


@mcp_tool(write_action=False)
async def get_workflow_run(full_name: str, run_id: int) -> Dict[str, Any]:
    """Retrieve a specific workflow run including timing and conclusion."""
    return await _github_request(
        "GET",
        f"/repos/{full_name}/actions/runs/{run_id}",
    )


@mcp_tool(write_action=False)
async def list_workflow_run_jobs(
    full_name: str,
    run_id: int,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List jobs within a workflow run, useful for troubleshooting failures."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/actions/runs/{run_id}/jobs",
        params=params,
    )


@mcp_tool(write_action=False)
async def get_workflow_run_overview(full_name: str, run_id: int) -> Dict[str, Any]:
    """Summarize a GitHub Actions workflow run for CI triage.

    This helper is read-only and safe to call before any write actions. It
    aggregates run metadata, jobs, failed jobs, and the longest jobs by
    duration so assistants can answer "what happened in this run?" with a
    single tool call.
    """

    run_resp = await get_workflow_run(full_name, run_id)
    run_json = run_resp.get("json") if isinstance(run_resp, dict) else run_resp
    if not isinstance(run_json, dict):
        run_json = {}

    run_summary: Dict[str, Any] = {
        "id": run_json.get("id"),
        "name": run_json.get("name"),
        "event": run_json.get("event"),
        "status": run_json.get("status"),
        "conclusion": run_json.get("conclusion"),
        "head_branch": run_json.get("head_branch"),
        "head_sha": run_json.get("head_sha"),
        "run_attempt": run_json.get("run_attempt"),
        "created_at": run_json.get("created_at"),
        "updated_at": run_json.get("updated_at"),
        "html_url": run_json.get("html_url"),
    }

    jobs_resp = await list_workflow_run_jobs(full_name, run_id, per_page=100, page=1)
    jobs_json = jobs_resp.get("json") or {}
    raw_jobs = jobs_json.get("jobs", []) if isinstance(jobs_json, dict) else []

    def _parse_timestamp(value: Any) -> Optional[datetime]:
        if not isinstance(value, str):
            return None
        try:
            if value.endswith("Z"):
                value = value[:-1] + "+00:00"
            return datetime.fromisoformat(value)
        except Exception:
            return None

    jobs: List[Dict[str, Any]] = []
    failed_jobs: List[Dict[str, Any]] = []
    jobs_with_duration: List[Dict[str, Any]] = []

    failure_conclusions = {
        "failure",
        "cancelled",
        "timed_out",
        "action_required",
        "startup_failure",
    }

    for job in raw_jobs:
        if not isinstance(job, dict):
            continue

        status = job.get("status")
        conclusion = job.get("conclusion")
        started_at = job.get("started_at")
        completed_at = job.get("completed_at")

        start_dt = _parse_timestamp(started_at)
        end_dt = _parse_timestamp(completed_at)
        duration_seconds: Optional[float] = None
        if start_dt and end_dt:
            duration_seconds = max(0.0, (end_dt - start_dt).total_seconds())

        normalized = {
            "id": job.get("id"),
            "name": job.get("name"),
            "status": status,
            "conclusion": conclusion,
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_seconds": duration_seconds,
            "html_url": job.get("html_url"),
        }
        jobs.append(normalized)

        if duration_seconds is not None:
            jobs_with_duration.append(normalized)

        include_failure = False
        if conclusion in failure_conclusions:
            include_failure = True
        elif status == "completed" and conclusion not in (None, "success", "neutral", "skipped"):
            include_failure = True
        if include_failure:
            failed_jobs.append(normalized)

    longest_jobs = sorted(
        jobs_with_duration,
        key=lambda j: j.get("duration_seconds") or 0.0,
        reverse=True,
    )[:5]

    return {
        "full_name": full_name,
        "run_id": run_id,
        "run": run_summary,
        "jobs": jobs,
        "failed_jobs": failed_jobs,
        "longest_jobs": longest_jobs,
    }


@mcp_tool(write_action=False)
async def get_job_logs(full_name: str, job_id: int) -> Dict[str, Any]:
    """Fetch raw logs for a GitHub Actions job without truncation."""

    client = _http_client_github or _github_client_instance()
    request = client.build_request(
        "GET",
        f"/repos/{full_name}/actions/jobs/{job_id}/logs",
        headers={"Accept": "application/vnd.github+json"},
    )
    async with _concurrency_semaphore:
        resp = await client.send(request, follow_redirects=True)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub job logs error {resp.status_code}: {resp.text}")
    content_type = resp.headers.get("Content-Type", "")
    if "zip" in content_type.lower():
        logs = _decode_zipped_job_logs(resp.content)
    else:
        logs = resp.text

    return {
        "status_code": resp.status_code,
        "logs": logs,
        "content_type": content_type,
    }


@mcp_tool(write_action=False)
async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """Poll a workflow run until completion or timeout."""

    client = _github_client_instance()
    end_time = asyncio.get_event_loop().time() + timeout_seconds

    while True:
        async with _concurrency_semaphore:
            resp = await client.get(
                f"/repos/{full_name}/actions/runs/{run_id}",
            )
        if resp.status_code >= 400:
            raise GitHubAPIError(f"GitHub workflow run error {resp.status_code}: {resp.text}")

        data = resp.json()
        status = data.get("status")
        conclusion = data.get("conclusion")

        if status == "completed":
            return {
                "status": status,
                "conclusion": conclusion,
                "run": data,
            }

        if asyncio.get_event_loop().time() > end_time:
            return {
                "status": status,
                "timeout": True,
                "run": data,
            }

        await asyncio.sleep(poll_interval_seconds)


@mcp_tool(
    write_action=False,
    description="Return a high-level overview of an issue, including related branches, pull requests, and checklist items, so assistants can decide what to do next.",
)
async def get_issue_overview(full_name: str, issue_number: int) -> Dict[str, Any]:
    """Summarize a GitHub issue for navigation and planning.

    This helper is intentionally read-only.
    It is designed for assistants to call before doing any write work so
    they understand the current state of an issue.
    """
    # Reuse the richer context helper so we see branches / PRs / labels, etc.
    context = await open_issue_context(full_name=full_name, issue_number=issue_number)
    issue = context.get("issue") or {}
    if not isinstance(issue, dict):
        issue = {}

    def _normalize_labels(raw: Any) -> List[Dict[str, Any]]:
        labels: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    labels.append(
                        {
                            "name": str(item.get("name", "")),
                            "color": item.get("color"),
                        }
                    )
                elif isinstance(item, str):
                    labels.append({"name": item})
        return labels

    def _normalize_user(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        login = raw.get("login")
        if not isinstance(login, str):
            return None
        return {"login": login, "html_url": raw.get("html_url")}

    def _normalize_assignees(raw: Any) -> List[Dict[str, Any]]:
        assignees: List[Dict[str, Any]] = []
        if isinstance(raw, list):
            for user in raw:
                normalized = _normalize_user(user)
                if normalized is not None:
                    assignees.append(normalized)
        return assignees

    # Core issue fields
    normalized_issue: Dict[str, Any] = {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "html_url": issue.get("html_url"),
        "created_at": issue.get("created_at"),
        "updated_at": issue.get("updated_at"),
        "closed_at": issue.get("closed_at"),
        "user": _normalize_user(issue.get("user")),
        "assignees": _normalize_assignees(issue.get("assignees")),
        "labels": _normalize_labels(issue.get("labels")),
    }

    body_text = issue.get("body") or ""

    def _extract_checklist_items(text: str, source: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = raw_line.lstrip()
            if line.startswith("- [ ") or line.startswith("- [") or line.startswith("* ["):
                checked = "[x]" in line.lower() or "[X]" in line
                # Strip the leading marker (e.g. "- [ ]" / "- [x]")
                after = line.split("]", 1)
                description = after[1].strip() if len(after) > 1 else raw_line.strip()
                if description:
                    items.append(
                        {
                            "text": description,
                            "checked": bool(checked),
                            "source": source,
                        }
                    )
        return items

    checklist_items: List[Dict[str, Any]] = []
    if body_text:
        checklist_items.extend(_extract_checklist_items(body_text, source="issue_body"))

    # Pull checklist items from comments as well, if available.
    comments = context.get("comments")
    if isinstance(comments, list):
        for comment in comments:
            if not isinstance(comment, dict):
                continue
            body = comment.get("body")
            if not isinstance(body, str) or not body.strip():
                continue
            checklist_items.extend(
                _extract_checklist_items(body, source="comment")
            )

    # Related branches / PRs are already computed by open_issue_context.
    candidate_branches = context.get("candidate_branches") or []
    open_prs = context.get("open_prs") or []
    closed_prs = context.get("closed_prs") or []

    return {
        "issue": normalized_issue,
        "candidate_branches": candidate_branches,
        "open_prs": open_prs,
        "closed_prs": closed_prs,
        "checklist_items": checklist_items,
    }


@mcp_tool(write_action=True)
async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Trigger a workflow dispatch event on the given ref.

    Args:
        full_name: "owner/repo" string.
        workflow: Workflow file name or ID (e.g. "ci.yml" or a numeric ID).
        ref: Git ref (branch, tag, or SHA) to run the workflow on.
        inputs: Optional input payload for workflows that declare inputs.
    """
    _ensure_write_allowed(f"trigger workflow {workflow} on {full_name}@{ref}")
    payload: Dict[str, Any] = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs
    client = _github_client_instance()
    async with _concurrency_semaphore:
        resp = await client.post(
            f"/repos/{full_name}/actions/workflows/{workflow}/dispatches",
            json=payload,
        )
    if resp.status_code not in (204, 201):
        raise GitHubAPIError(
            f"GitHub workflow dispatch error {resp.status_code}: {resp.text}"
        )
    return {"status_code": resp.status_code}


@mcp_tool(write_action=True)
async def trigger_and_wait_for_workflow(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """Trigger a workflow and block until it completes or hits timeout."""

    _ensure_write_allowed(f"trigger+wait workflow {workflow} on {full_name}@{ref}")
    await trigger_workflow_dispatch(full_name, workflow, ref, inputs)

    runs = await list_workflow_runs(
        full_name,
        branch=ref,
        per_page=1,
        page=1,
    )
    workflow_runs = runs.get("json", {}).get("workflow_runs", [])
    if not workflow_runs:
        raise GitHubAPIError("No workflow runs found after dispatch")
    run_id = workflow_runs[0]["id"]

    result = await wait_for_workflow_run(full_name, run_id, timeout_seconds, poll_interval_seconds)
    return {"run_id": run_id, "result": result}


# ------------------------------------------------------------------------------
# PR / issue management tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
async def list_pull_requests(
    full_name: str,
    state: str = "open",
    head: Optional[str] = None,
    base: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List pull requests with optional head/base filters.

    Args:
        full_name: "owner/repo" string.
        state: One of 'open', 'closed', or 'all'.
        head: Optional head filter of the form 'user:branch'.
        base: Optional base branch filter.
        per_page: Number of results per page (must be > 0).
        page: Page number for pagination (must be > 0).
    """

    allowed_states = {"open", "closed", "all"}
    if state not in allowed_states:
        raise ValueError("state must be 'open', 'closed', or 'all'")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    params: Dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
    if head:
        params["head"] = head
    if base:
        params["base"] = base
    return await _github_request("GET", f"/repos/{full_name}/pulls", params=params)


@mcp_tool(write_action=True)
async def merge_pull_request(
    full_name: str,
    number: int,
    merge_method: str = "squash",
    commit_title: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge a pull request using squash (default), merge, or rebase.

    Args:
        full_name: "owner/repo" string.
        number: Pull request number.
        merge_method: One of 'merge', 'squash', or 'rebase'.
        commit_title: Optional custom commit title.
        commit_message: Optional custom commit message.
    """

    allowed_methods = {"merge", "squash", "rebase"}
    if merge_method not in allowed_methods:
        raise ValueError("merge_method must be 'merge', 'squash', or 'rebase'")

    _ensure_write_allowed(f"merge PR #{number} in {full_name}")
    payload: Dict[str, Any] = {"merge_method": merge_method}
    if commit_title is not None:
        payload["commit_title"] = commit_title
    if commit_message is not None:
        payload["commit_message"] = commit_message
    return await _github_request("PUT", f"/repos/{full_name}/pulls/{number}/merge", json_body=payload)


@mcp_tool(write_action=True)
async def close_pull_request(full_name: str, number: int) -> Dict[str, Any]:
    """Close a pull request without merging."""

    _ensure_write_allowed(f"close PR #{number} in {full_name}")
    return await _github_request(
        "PATCH",
        f"/repos/{full_name}/pulls/{number}",
        json_body={"state": "closed"},
    )


@mcp_tool(write_action=True)
async def comment_on_pull_request(
    full_name: str,
    number: int,
    body: str,
) -> Dict[str, Any]:
    """Post a comment on a pull request (issue API under the hood)."""

    _ensure_write_allowed(f"comment on PR #{number} in {full_name}")
    return await _github_request(
        "POST",
        f"/repos/{full_name}/issues/{number}/comments",
        json_body={"body": body},
    )


@mcp_tool(write_action=True)
async def create_issue(
    full_name: str,
    title: str,
    body: Optional[str] = None,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    # Create a GitHub issue with optional body, labels, and assignees.

    if "/" not in full_name:
        raise ValueError("full_name must be in owner/repo format")

    _ensure_write_allowed(f"create issue in {full_name}: {title!r}")

    payload: Dict[str, Any] = {"title": title}
    if body is not None:
        payload["body"] = body
    if labels is not None:
        payload["labels"] = labels
    if assignees is not None:
        payload["assignees"] = assignees

    return await _github_request(
        "POST",
        f"/repos/{full_name}/issues",
        json_body=payload,
    )


@mcp_tool(write_action=True)
async def update_issue(
    full_name: str,
    issue_number: int,
    title: Optional[str] = None,
    body: Optional[str] = None,
    state: Optional[str] = None,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    # Update fields on an existing GitHub issue.

    if "/" not in full_name:
        raise ValueError("full_name must be in owner/repo format")

    _ensure_write_allowed(f"update issue #{issue_number} in {full_name}")

    payload: Dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if body is not None:
        payload["body"] = body
    if state is not None:
        allowed_states = {"open", "closed"}
        if state not in allowed_states:
            raise ValueError("state must be 'open' or 'closed'")
        payload["state"] = state
    if labels is not None:
        payload["labels"] = labels
    if assignees is not None:
        payload["assignees"] = assignees

    if not payload:
        raise ValueError("At least one field must be provided to update_issue")

    return await _github_request(
        "PATCH",
        f"/repos/{full_name}/issues/{issue_number}",
        json_body=payload,
    )


@mcp_tool(write_action=True)
async def comment_on_issue(
    full_name: str,
    issue_number: int,
    body: str,
) -> Dict[str, Any]:
    # Post a comment on an issue.

    if "/" not in full_name:
        raise ValueError("full_name must be in owner/repo format")

    _ensure_write_allowed(f"comment on issue #{issue_number} in {full_name}")

    return await _github_request(
        "POST",
        f"/repos/{full_name}/issues/{issue_number}/comments",
        json_body={"body": body},
    )


@mcp_tool(write_action=False)
async def open_issue_context(full_name: str, issue_number: int) -> Dict[str, Any]:
    """Return an issue plus related branches and pull requests."""

    issue_resp = await fetch_issue(full_name, issue_number)
    issue_json = issue_resp.get("json") if isinstance(issue_resp, dict) else issue_resp

    branches_resp = await list_branches(full_name, per_page=100)
    branches_json = branches_resp.get("json") or []
    branch_names = [b.get("name") for b in branches_json if isinstance(b, dict)]

    pattern = re.compile(rf"(?i)(?:^|[-_/]){re.escape(str(issue_number))}(?:$|[-_/])")
    candidate_branches = [
        name for name in branch_names if isinstance(name, str) and pattern.search(name)
    ]

    prs_resp = await list_pull_requests(full_name, state="all")
    prs = prs_resp.get("json") or []

    issue_str = str(issue_number)
    open_prs: List[Dict[str, Any]] = []
    closed_prs: List[Dict[str, Any]] = []
    for pr in prs:
        if not isinstance(pr, dict):
            continue
        branch_name = pr.get("head", {}).get("ref")
        text = f"{pr.get('title', '')}\n{pr.get('body', '')}"
        if issue_str in text or (isinstance(branch_name, str) and issue_str in branch_name):
            target_list = open_prs if pr.get("state") == "open" else closed_prs
            target_list.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "draft": pr.get("draft"),
                    "html_url": pr.get("html_url"),
                    "head": pr.get("head"),
                    "base": pr.get("base"),
                }
            )

    return {
        "issue": issue_json,
        "candidate_branches": candidate_branches,
        "open_prs": open_prs,
        "closed_prs": closed_prs,
    }


def _normalize_issue_payload(raw_issue: Any) -> Optional[Dict[str, Any]]:
    issue = raw_issue
    if isinstance(raw_issue, dict) and "json" in raw_issue:
        issue = raw_issue.get("json")
    if not isinstance(issue, dict):
        return None

    user = issue.get("user") if isinstance(issue.get("user"), dict) else None
    labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []

    return {
        "number": issue.get("number"),
        "title": issue.get("title"),
        "state": issue.get("state"),
        "html_url": issue.get("html_url"),
        "user": user.get("login") if user else None,
        "labels": [lbl.get("name") for lbl in labels if isinstance(lbl, dict)],
    }


def _normalize_pr_payload(raw_pr: Any) -> Optional[Dict[str, Any]]:
    pr = raw_pr
    if isinstance(raw_pr, dict) and "json" in raw_pr:
        pr = raw_pr.get("json")
    if not isinstance(pr, dict):
        return None

    user = pr.get("user") if isinstance(pr.get("user"), dict) else None
    head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
    base = pr.get("base") if isinstance(pr.get("base"), dict) else {}

    return {
        "number": pr.get("number"),
        "title": pr.get("title"),
        "state": pr.get("state"),
        "draft": pr.get("draft"),
        "merged": pr.get("merged"),
        "html_url": pr.get("html_url"),
        "user": user.get("login") if user else None,
        "head_ref": head.get("ref"),
        "base_ref": base.get("ref"),
    }


def _normalize_branch_summary(summary: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(summary, dict):
        return None

    if summary.get("compare_error") and not summary.get("compare"):
        return None

    compare = summary.get("compare") if isinstance(summary.get("compare"), dict) else None
    compare_normalized = None
    if compare:
        compare_normalized = {
            "ahead_by": compare.get("ahead_by"),
            "behind_by": compare.get("behind_by"),
            "total_commits": compare.get("total_commits"),
            "status": compare.get("status"),
        }

    def _simplify_prs(prs: Any) -> list[Dict[str, Any]]:
        simplified: list[Dict[str, Any]] = []
        if not isinstance(prs, list):
            return simplified
        for pr in prs:
            if not isinstance(pr, dict):
                continue
            head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
            base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
            simplified.append(
                {
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "state": pr.get("state"),
                    "draft": pr.get("draft"),
                    "html_url": pr.get("html_url"),
                    "head_ref": head.get("ref"),
                    "base_ref": base.get("ref"),
                }
            )
        return simplified

    latest_run = summary.get("latest_workflow_run")
    latest_run_normalized = None
    if isinstance(latest_run, dict):
        latest_run_normalized = {
            "id": latest_run.get("id"),
            "status": latest_run.get("status"),
            "conclusion": latest_run.get("conclusion"),
            "html_url": latest_run.get("html_url"),
            "head_branch": latest_run.get("head_branch"),
        }

    normalized = {
        "branch": summary.get("branch"),
        "base": summary.get("base"),
        "compare": compare_normalized,
        "open_prs": _simplify_prs(summary.get("open_prs")),
        "closed_prs": _simplify_prs(summary.get("closed_prs")),
        "latest_workflow_run": latest_run_normalized,
    }

    if all(value is None or value == [] for value in normalized.values()):
        return None

    return normalized


@mcp_tool(write_action=False)
async def resolve_handle(full_name: str, handle: str) -> Dict[str, Any]:
    """Resolve a lightweight GitHub handle into issue, PR, or branch details.

    Examples:
        - ``resolve_handle(full_name="owner/repo", handle="123")``
        - ``resolve_handle(full_name="owner/repo", handle="#456")``
        - ``resolve_handle(full_name="owner/repo", handle="pr:789")``
        - ``resolve_handle(full_name="owner/repo", handle="feature/awesome")``
    """

    original_handle = handle
    handle = handle.strip()
    lower_handle = handle.lower()

    resolved_kinds: list[str] = []
    issue: Optional[Dict[str, Any]] = None
    pull_request: Optional[Dict[str, Any]] = None
    branch: Optional[Dict[str, Any]] = None

    def _append_kind(name: str, value: Optional[Dict[str, Any]]):
        if value is not None:
            resolved_kinds.append(name)

    async def _try_fetch_issue(number: int) -> Optional[Dict[str, Any]]:
        try:
            result = await fetch_issue(full_name, number)
        except Exception:
            return None
        return _normalize_issue_payload(result)

    async def _try_fetch_pr(number: int) -> Optional[Dict[str, Any]]:
        try:
            result = await fetch_pr(full_name, number)
        except Exception:
            return None
        return _normalize_pr_payload(result)

    async def _try_fetch_branch(name: str) -> Optional[Dict[str, Any]]:
        try:
            result = await get_branch_summary(full_name, name)
        except Exception:
            return None
        return _normalize_branch_summary(result)

    def _parse_int(value: str) -> Optional[int]:
        value = value.strip()
        if not value.isdigit():
            return None
        try:
            return int(value)
        except ValueError:
            return None

    number: Optional[int] = None

    if lower_handle.startswith("issue:"):
        number = _parse_int(handle.split(":", 1)[1])
        if number is not None:
            issue = await _try_fetch_issue(number)
            _append_kind("issue", issue)
    elif lower_handle.startswith("pr:"):
        number = _parse_int(handle.split(":", 1)[1])
        if number is not None:
            pull_request = await _try_fetch_pr(number)
            _append_kind("pull_request", pull_request)
    else:
        numeric_match = re.fullmatch(r"#?(\d+)", handle)
        trailing_match = re.search(r"#(\d+)$", handle)
        if numeric_match:
            number = int(numeric_match.group(1))
        elif trailing_match:
            number = int(trailing_match.group(1))

        if number is not None:
            issue = await _try_fetch_issue(number)
            _append_kind("issue", issue)

            pull_request = await _try_fetch_pr(number)
            _append_kind("pull_request", pull_request)
        else:
            branch = await _try_fetch_branch(handle)
            _append_kind("branch", branch)

    return {
        "input": {"full_name": full_name, "handle": original_handle},
        "issue": issue,
        "pull_request": pull_request,
        "branch": branch,
        "resolved_kinds": resolved_kinds,
    }


@mcp_tool(write_action=False)
async def compare_refs(
    full_name: str,
    base: str,
    head: str,
) -> Dict[str, Any]:
    """Compare two refs and return the GitHub diff summary (max 100 files)."""

    data = await _github_request(
        "GET",
        f"/repos/{full_name}/compare/{base}...{head}",
    )
    j = data.get("json") or {}
    files = j.get("files", [])
    return {**j, "files": files[:100]}


# ------------------------------------------------------------------------------
# Branch / commit / PR helpers
# ------------------------------------------------------------------------------


@mcp_tool(write_action=True)
async def create_branch(
    full_name: str,
    new_branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """Create a new branch from an existing ref (default ``main``)."""

    _ensure_write_allowed(f"create branch {new_branch} from {from_ref} in {full_name}")
    sha = await _get_branch_sha(full_name, from_ref)
    payload = {"ref": f"refs/heads/{new_branch}", "sha": sha}
    return await _github_request(
        "POST",
        f"/repos/{full_name}/git/refs",
        json_body=payload,
    )


@mcp_tool(write_action=True)
async def ensure_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """Idempotently ensure a branch exists, creating it from ``from_ref``."""

    _ensure_write_allowed(f"ensure branch {branch} from {from_ref} in {full_name}")
    client = _github_client_instance()
    async with _concurrency_semaphore:
        resp = await client.get(f"/repos/{full_name}/git/ref/heads/{branch}")
    if resp.status_code == 404:
        return await create_branch(full_name, branch, from_ref)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub ensure_branch error {resp.status_code}: {resp.text}")
    return {"status_code": resp.status_code, "json": resp.json()}


@mcp_tool(write_action=False)
async def get_branch_summary(full_name: str, branch: str, base: str = "main") -> Dict[str, Any]:
    """Return ahead/behind data, PRs, and latest workflow run for a branch."""

    effective_branch = _effective_ref_for_repo(full_name, branch)
    effective_base = _effective_ref_for_repo(full_name, base)

    compare_result: Optional[Dict[str, Any]] = None
    compare_error: Optional[str] = None
    try:
        compare_result = await compare_refs(full_name, effective_base, effective_branch)
    except Exception as exc:
        compare_error = str(exc)

    owner: Optional[str] = None
    if "/" in full_name:
        owner = full_name.split("/", 1)[0]
    head_param = f"{owner}:{effective_branch}" if owner else None

    async def _safe_list_prs(state: str) -> Dict[str, Any]:
        try:
            return await list_pull_requests(
                full_name, state=state, head=head_param, base=effective_base
            )
        except Exception as exc:  # pragma: no cover - defensive
            return {"error": str(exc), "json": []}

    open_prs_resp = await _safe_list_prs("open")
    closed_prs_resp = await _safe_list_prs("closed")

    open_prs = open_prs_resp.get("json") or []
    closed_prs = closed_prs_resp.get("json") or []

    workflow_error: Optional[str] = None
    latest_workflow_run: Optional[Dict[str, Any]] = None
    try:
        runs_resp = await list_workflow_runs(full_name, branch=effective_branch, per_page=1)
        runs_json = runs_resp.get("json") or {}
        runs = runs_json.get("workflow_runs", []) if isinstance(runs_json, dict) else []
        if runs:
            latest_workflow_run = runs[0]
    except Exception as exc:
        workflow_error = str(exc)

    return {
        "full_name": full_name,
        "branch": effective_branch,
        "base": effective_base,
        "compare": compare_result,
        "compare_error": compare_error,
        "open_prs": open_prs,
        "closed_prs": closed_prs,
        "latest_workflow_run": latest_workflow_run,
        "workflow_error": workflow_error,
    }


@mcp_tool(write_action=False)
async def get_latest_branch_status(full_name: str, branch: str, base: str = "main") -> Dict[str, Any]:
    """Return a normalized, assistant-friendly view of the latest status for a branch.

    This wraps ``get_branch_summary`` and ``_normalize_branch_summary`` so controllers
    and assistants can quickly answer questions like:

      - "Is this branch ahead or behind the base?"
      - "Is there an open PR for it?"
      - "What was the latest workflow run and how did it finish?"
    """

    summary = await get_branch_summary(full_name, branch, base=base)
    normalized = _normalize_branch_summary(summary)

    # Always return a consistent shape so callers do not have to special-case
    # "no data" situations; instead they can look at the ``normalized`` field
    # and fall back to the raw summary if needed.
    return {
        "full_name": full_name,
        "branch": summary.get("branch"),
        "base": summary.get("base"),
        "summary": summary,
        "normalized": normalized,
    }


@mcp_tool(write_action=False)
async def get_repo_dashboard(full_name: str, branch: Optional[str] = None) -> Dict[str, Any]:
    """Return a compact, multi-signal dashboard for a repository.

    This helper aggregates several lower-level tools into a single call so
    assistants can quickly understand the current state of a repo and then
    decide which focused tools to call next. It is intentionally read-only.

    Args:
        full_name:
            "owner/repo" string.
        branch:
            Optional branch name. When omitted, the repository's default
            branch is used via the same normalization logic as other tools.

    Returns:
        A dict with high-level fields such as:

          - repo: core metadata about the repository (description, visibility,
            default branch, topics, open issue count when available).
          - branch: the effective branch used for lookups.
          - pull_requests: a small window of open pull requests (up to 10).
          - issues: a small window of open issues (up to 10, excluding PRs).
          - workflows: recent GitHub Actions workflow runs on the branch
            (up to 5).
          - top_level_tree: compact listing of top-level files/directories
            on the branch so assistants can see the project layout.

        Individual sections degrade gracefully: if one underlying call fails,
        its corresponding "*_error" field is populated instead of raising.
    """

    # Resolve the effective branch using the same helper as other tools.
    if branch is None:
        # Fall back to the default branch when available.
        defaults = await get_repo_defaults(full_name)
        repo_defaults = defaults.get("defaults") or {}
        effective_branch = repo_defaults.get("default_branch") or _effective_ref_for_repo(
            full_name,
            "main",
        )
    else:
        effective_branch = _effective_ref_for_repo(full_name, branch)

    # --- Repository metadata ---
    repo_info: Optional[Dict[str, Any]] = None
    repo_error: Optional[str] = None
    try:
        repo_resp = await get_repository(full_name)
        repo_info = repo_resp.get("json") or {}
    except Exception as exc:  # pragma: no cover - defensive
        repo_error = str(exc)

    # --- Open pull requests (small window) ---
    pr_error: Optional[str] = None
    open_prs: list[Dict[str, Any]] = []
    try:
        pr_resp = await list_pull_requests(
            full_name,
            state="open",
            per_page=10,
            page=1,
        )
        open_prs = pr_resp.get("json") or []
    except Exception as exc:  # pragma: no cover - defensive
        pr_error = str(exc)

    # --- Open issues (excluding PRs) ---
    issues_error: Optional[str] = None
    open_issues: list[Dict[str, Any]] = []
    try:
        issues_resp = await list_repository_issues(
            full_name,
            state="open",
            per_page=10,
            page=1,
        )
        raw_issues = issues_resp.get("json") or []
        # Filter out pull requests that show up in the issues API.
        for item in raw_issues:
            if isinstance(item, dict) and "pull_request" not in item:
                open_issues.append(item)
    except Exception as exc:  # pragma: no cover - defensive
        issues_error = str(exc)

    # --- Recent workflow runs on this branch ---
    workflows_error: Optional[str] = None
    workflow_runs: list[Dict[str, Any]] = []
    try:
        runs_resp = await list_workflow_runs(
            full_name,
            branch=effective_branch,
            per_page=5,
            page=1,
        )
        runs_json = runs_resp.get("json") or {}
        workflow_runs = (
            runs_json.get("workflow_runs", [])
            if isinstance(runs_json, dict)
            else []
        )
    except Exception as exc:  # pragma: no cover - defensive
        workflows_error = str(exc)

    # --- Top-level tree entries on the branch ---
    tree_error: Optional[str] = None
    top_level_tree: list[Dict[str, Any]] = []
    try:
        tree_resp = await list_repository_tree(
            full_name,
            ref=effective_branch,
            recursive=False,
            max_entries=200,
        )
        entries = tree_resp.get("entries") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            # Keep only top-level entries (no slashes) for a compact view.
            if "/" in path:
                continue
            top_level_tree.append(
                {
                    "path": path,
                    "type": entry.get("type"),
                    "size": entry.get("size"),
                }
            )
    except Exception as exc:  # pragma: no cover - defensive
        tree_error = str(exc)

    return {
        "full_name": full_name,
        "branch": effective_branch,
        "repo": repo_info,
        "repo_error": repo_error,
        "pull_requests": open_prs,
        "pull_requests_error": pr_error,
        "issues": open_issues,
        "issues_error": issues_error,
        "workflows": workflow_runs,
        "workflows_error": workflows_error,
        "top_level_tree": top_level_tree,
        "top_level_tree_error": tree_error,
    }


@mcp_tool(write_action=True)
async def create_pull_request(
    full_name: str,
    title: str,
    head: str,
    base: str = "main",
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """Open a pull request from ``head`` into ``base``.

    The base branch is normalized via ``_effective_ref_for_repo`` so that
    controller repos honor the configured default branch when callers supply
    ``main`` or omit the ref. This keeps PR targets consistent even when the
    controller prompt tells assistants to open PRs against main.
    """

    effective_base = _effective_ref_for_repo(full_name, base)
    _ensure_write_allowed(
        f"create PR from {head} to {effective_base} in {full_name}"
    )

    payload: Dict[str, Any] = {
        "title": title,
        "head": head,
        "base": effective_base,
        "draft": draft,
    }
    if body is not None:
        payload["body"] = body

    try:
        return await _github_request(
            "POST",
            f"/repos/{full_name}/pulls",
            json_body=payload,
        )
    except Exception as exc:
        return _structured_tool_error(exc, context="create_pull_request")


@mcp_tool(write_action=True)
async def open_pr_for_existing_branch(
    full_name: str,
    branch: str,
    base: str = "main",
    title: Optional[str] = None,
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """Open a pull request for an existing branch into a base branch.

    This helper is intentionally idempotent: if there is already an open PR for
    the same head/base pair, it will return that existing PR instead of failing
    or creating a duplicate.
    """

    # Resolve the effective base branch using the same logic as other helpers.
    effective_base = _effective_ref_for_repo(full_name, base)
    pr_title = title or f"{branch} -> {effective_base}"

    # GitHub's API expects the head in the form "owner:branch" when used
    # with the head filter on the pulls listing endpoint.
    owner, _repo = full_name.split("/", 1)
    head_ref = f"{owner}:{branch}"

    # 1) Check for an existing open PR for this head/base pair.
    existing_json: Any = []
    try:
        existing_resp = await list_pull_requests(
            full_name,
            state="open",
            head=head_ref,
            base=effective_base,
            per_page=10,
            page=1,
        )
        existing_json = existing_resp.get("json") or []
    except Exception as exc:
        # If listing PRs fails for any reason, surface the structured error
        # details back to the caller instead of silently claiming success.
        return _structured_tool_error(exc, context="open_pr_for_existing_branch:list_pull_requests")

    if isinstance(existing_json, list) and existing_json:
        # Reuse the first matching PR, and normalize the shape so assistants can
        # consistently see the PR number/URL.
        pr_obj = existing_json[0]
        if isinstance(pr_obj, dict):
            return {
                "status": "ok",
                "reused_existing": True,
                "pull_request": pr_obj,
                "pr_number": pr_obj.get("number"),
                "pr_url": pr_obj.get("html_url"),
            }
        return {
            "status": "error",
            "message": "Existing PR listing returned a non-dict entry",
            "raw_entry": pr_obj,
        }

    # 2) No existing PR found; create a new one via the lower-level helper.
    pr = await create_pull_request(
        full_name=full_name,
        title=pr_title,
        head=branch,
        base=effective_base,
        body=body,
        draft=draft,
    )

    pr_json = pr.get("json") or {}
    if not isinstance(pr_json, dict) or not pr_json.get("number"):
        # Bubble through the structured error shape so the caller can inspect
        # status/message and decide how to recover.
        return {
            "status": "error",
            "raw_response": pr,
            "message": "create_pull_request did not return a PR document with a number",
        }

    return {
        "status": "ok",
        "pull_request": pr_json,
        "pr_number": pr_json.get("number"),
        "pr_url": pr_json.get("html_url"),
    }

@mcp_tool(write_action=True)
async def update_files_and_open_pr(
    full_name: str,
    title: str,
    files: List[Dict[str, Any]],
    base_branch: str = "main",
    new_branch: Optional[str] = None,
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """Commit multiple files, verify each, then open a PR in one call."""

    current_path: Optional[str] = None
    try:
        effective_base = _effective_ref_for_repo(full_name, base_branch)

        if not files:
            raise ValueError("files must contain at least one item")

        # 1) Ensure a dedicated branch exists
        branch = new_branch or f"ally-{os.urandom(4).hex()}"
        _ensure_write_allowed("update_files_and_open_pr %s %s" % (full_name, branch), target_ref=branch)
        await ensure_branch(full_name, branch, from_ref=effective_base)

        commit_results: List[Dict[str, Any]] = []
        verifications: List[Dict[str, Any]] = []

        # 2) Commit each file, with verification
        for f in files:
            current_path = f.get("path")
            if not current_path:
                raise ValueError("Each file dict must include a 'path' key")

            file_message = f.get("message") or title
            file_content = f.get("content")
            file_content_url = f.get("content_url")

            if file_content is None and file_content_url is None:
                raise ValueError(
                    f"File entry for {current_path!r} must specify "
                    "either 'content' or 'content_url'"
                )
            if file_content is not None and file_content_url is not None:
                raise ValueError(
                    f"File entry for {current_path!r} may not specify both "
                    "'content' and 'content_url'"
                )

            # Load content
            if file_content_url is not None:
                try:
                    body_bytes = await _load_body_from_content_url(
                        file_content_url,
                        context=(f"update_files_and_open_pr({full_name}/{current_path})"),
                    )
                except Exception as exc:
                    return _structured_tool_error(
                        exc,
                        context="update_files_and_open_pr.load_content",
                        path=current_path,
                    )
            else:
                body_bytes = file_content.encode("utf-8")

            # Resolve SHA and commit
            try:
                sha = await _resolve_file_sha(full_name, current_path, branch)
                commit_result = await _perform_github_commit(
                    full_name=full_name,
                    path=current_path,
                    message=file_message,
                    branch=branch,
                    body_bytes=body_bytes,
                    sha=sha,
                )
            except Exception as exc:
                return _structured_tool_error(
                    exc,
                    context="update_files_and_open_pr.commit_file",
                    path=current_path,
                )

            commit_results.append(
                {
                    "path": current_path,
                    "message": file_message,
                    "result": commit_result,
                }
            )

            # Post-commit verification for this file
            try:
                verification = await _verify_file_on_branch(full_name, current_path, branch)
            except Exception as exc:
                return _structured_tool_error(
                    exc,
                    context="update_files_and_open_pr.verify_file",
                    path=current_path,
                )

            verifications.append(verification)

        # 3) Open the PR
        try:
            pr = await create_pull_request(
                full_name=full_name,
                title=title,
                head=branch,
                base=effective_base,
                body=body,
                draft=draft,
            )
        except Exception as exc:
            return _structured_tool_error(
                exc, context="update_files_and_open_pr.create_pr", path=current_path
            )

        return {
            "branch": branch,
            "pull_request": pr,
            "commits": commit_results,
            "verifications": verifications,
        }

    except Exception as exc:
        return _structured_tool_error(exc, context="update_files_and_open_pr", path=current_path)



@mcp_tool(write_action=True)
async def create_file(
    full_name: str,
    path: str,
    content: str,
    *,
    branch: str = "main",
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new text file in a repository.

    The call fails if the file already exists on the target branch.

    Args:
        full_name: "owner/repo" string.
        path: Path of the file within the repository.
        content: UTF-8 text content of the new file.
        branch: Branch to commit to (default "main").
        message: Optional commit message; if omitted, a default is derived.

    Returns:
        A dict with:
            - status: "created"
            - full_name, path, branch
            - message: The commit message used.
            - commit: Raw commit response from GitHub.
            - verification: A dict containing sha_before (always None),
              sha_after and html_url from a fresh read of the file.
    """

    effective_branch = _effective_ref_for_repo(full_name, branch)

    _ensure_write_allowed(
        "create_file %s %s" % (full_name, path),
        target_ref=effective_branch,
    )

    # Ensure the file does not already exist.
    try:
        await _decode_github_content(full_name, path, effective_branch)
    except GitHubAPIError as exc:
        msg = str(exc)
        if "404" in msg and "/contents/" in msg:
            sha_before: Optional[str] = None
        else:
            raise
    else:
        raise GitHubAPIError(
            f"File already exists at {path} on branch {effective_branch}"
        )

    body_bytes = content.encode("utf-8")
    commit_message = message or f"Create {path}"

    commit_result = await _perform_github_commit(
        full_name=full_name,
        path=path,
        message=commit_message,
        body_bytes=body_bytes,
        branch=effective_branch,
        sha=sha_before,
    )

    verified = await _decode_github_content(full_name, path, effective_branch)
    json_blob = verified.get("json")
    sha_after: Optional[str]
    if isinstance(json_blob, dict) and isinstance(json_blob.get("sha"), str):
        sha_after = json_blob["sha"]
    else:
        sha_value = verified.get("sha")
        sha_after = sha_value if isinstance(sha_value, str) else None

    return {
        "status": "created",
        "full_name": full_name,
        "path": path,
        "branch": effective_branch,
        "message": commit_message,
        "commit": commit_result,
        "verification": {
            "sha_before": sha_before,
            "sha_after": sha_after,
            "html_url": verified.get("html_url"),
        },
    }
            "branch": effective_branch,
            "message": commit_message,
            "commit": commit_result,
            "verification": {
                "sha_before": sha_before,
                "sha_after": sha_after,
                "html_url": verified.get("html_url"),
            },
        }


@mcp_tool(write_action=True)
async def apply_text_update_and_commit(
    full_name: str,
    path: str,
    updated_content: str,
    *,
    branch: str = "main",
    message: Optional[str] = None,
    return_diff: bool = True,
    context_lines: int = 3,
) -> Dict[str, Any]:
    """Apply a text update to a single file on a branch, then verify it.

    This is a lower-level building block for diff-based flows:

    1. Read the current file text from GitHub.
    2. Commit the provided updated_content via the Contents API on the target branch.
    3. Re-read the file to verify the new SHA and contents landed.
    4. Optionally compute and return a unified diff between old and new text.

    It does NOT create a PR; callers are expected to open a PR separately
    (for example using create_pull_request or update_files_and_open_pr) if
    they want reviewable changes.

    Args:
        full_name: "owner/repo" string.
        path: Path of the file within the repository.
        updated_content: New full text for the file (UTF-8).
        branch: Branch to commit to (default "main").
        message: Commit message; if omitted, a simple "Update <path>" is used.
        return_diff: If true, include a unified diff in the response under "diff".
        context_lines: Number of context lines for the unified diff.

    Returns:
        A dict with:
            - status: "committed"
            - full_name, path, branch
            - message: commit message used
            - commit: raw GitHub commit API response
            - verification: {sha_before, sha_after, html_url}
            - diff: unified diff text (if return_diff is true)
    """

    if context_lines < 0:
        raise ValueError("context_lines must be non-negative")

    effective_branch = _effective_ref_for_repo(full_name, branch)

    _ensure_write_allowed("apply_text_update_and_commit %s %s" % (full_name, path), target_ref=effective_branch)

    # 1) Read the current file state on the target branch, treating a 404 as a new file.
    is_new_file = False

    def _extract_sha(decoded: Dict[str, Any]) -> Optional[str]:
        if not isinstance(decoded, dict):
            return None
        json_blob = decoded.get("json")
        if isinstance(json_blob, dict) and isinstance(json_blob.get("sha"), str):
            return json_blob.get("sha")
        sha_value = decoded.get("sha")
        return sha_value if isinstance(sha_value, str) else None

    try:
        decoded = await _decode_github_content(full_name, path, effective_branch)
        old_text = decoded.get("text")
        if not isinstance(old_text, str):
            raise GitHubAPIError("Decoded content is not text")
        sha_before = _extract_sha(decoded)
    except GitHubAPIError as exc:
        msg = str(exc)
        if "404" in msg and "/contents/" in msg:
            # The GitHub Contents API returns 404 when the file does not yet exist.
            # In that case we treat this as a creation rather than an update.
            is_new_file = True
            old_text = ""
            sha_before = None
        else:
            raise

    body_bytes = updated_content.encode("utf-8")
    if message is not None:
        commit_message = message
    elif is_new_file:
        commit_message = f"Create {path}"
    else:
        commit_message = f"Update {path}"

    # 2) Commit the new content via the GitHub Contents API.
    commit_result = await _perform_github_commit(
        full_name=full_name,
        path=path,
        message=commit_message,
        body_bytes=body_bytes,
        branch=effective_branch,
        sha=sha_before,
    )

    # 3) Verify by reading the file again from the same branch.
    verified = await _decode_github_content(full_name, path, effective_branch)
    new_text = verified.get("text")
    sha_after = _extract_sha(verified)

    result: Dict[str, Any] = {
        "status": "committed",
        "full_name": full_name,
        "path": path,
        "branch": effective_branch,
        "message": commit_message,
        "commit": commit_result,
        "verification": {
            "sha_before": sha_before,
            "sha_after": sha_after,
            "html_url": verified.get("html_url"),
        },
    }

    # 4) Optionally compute a unified diff between the old and new text.
    if return_diff:
        import difflib

        diff_iter = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            (new_text or "").splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=context_lines,
        )
        result["diff"] = "".join(diff_iter)

    return result


@mcp_tool(write_action=True)
async def apply_patch_and_commit(
    full_name: str,
    path: str,
    patch: str,
    *,
    branch: str = 'main',
    message: Optional[str] = None,
    return_diff: bool = True,
) -> Dict[str, Any]:
    '''Apply a unified diff to a single file, commit it, then verify it.

    This is a first-class patch-based flow for a single file:

      1. Read the current file text from GitHub on the given branch.
      2. Apply a unified diff (for that file) in memory.
      3. Commit the resulting text via the GitHub Contents API.
      4. Re-read the file on the branch to verify the new SHA and contents.

    The patch is expected to be a standard unified diff for *this* path,
    typically generated by `build_unified_diff` against the same branch.

    Args:
        full_name: 'owner/repo' string.
        path: Path of the file within the repository.
        patch: Unified diff text affecting this path only.
        branch: Branch to commit to (default 'main').
        message: Commit message; if omitted, a default is derived.
        return_diff: If true, include a recomputed unified diff between the
            old and new text (not just echo the incoming patch).

    Returns:
        A dict with:
            - status: 'committed'
            - full_name, path, branch
            - message: commit message used
            - commit: raw GitHub commit API response
            - verification: {sha_before, sha_after, html_url}
            - diff: unified diff text (if return_diff is true)
    '''

    effective_branch = _effective_ref_for_repo(full_name, branch)

    _ensure_write_allowed(
        'apply_patch_and_commit %s %s' % (full_name, path),
        target_ref=effective_branch,
    )

    import re
    import difflib

    def _extract_paths_from_patch(patch_text: str) -> set[str]:
        '''Return the set of file paths mentioned in ---/+++ headers (normalized).

        Paths are normalized by stripping leading a/ or b/ prefixes.
        /dev/null entries are ignored.
        '''
        paths: set[str] = set()
        for line in patch_text.splitlines():
            if not (line.startswith('--- ') or line.startswith('+++ ')):
                continue
            _, raw = line.split(' ', 1)
            raw = raw.strip()
            if raw == '/dev/null':
                continue
            if raw.startswith('a/') or raw.startswith('b/'):
                raw = raw[2:]
            if raw:
                paths.add(raw)
        return paths

    def _extract_sha(decoded: Dict[str, Any]) -> Optional[str]:
        if not isinstance(decoded, dict):
            return None
        json_blob = decoded.get('json')
        if isinstance(json_blob, dict) and isinstance(json_blob.get('sha'), str):
            return json_blob.get('sha')
        sha_value = decoded.get('sha')
        return sha_value if isinstance(sha_value, str) else None

    def _apply_unified_diff_to_text(original_text: str, patch_text: str) -> str:
        '''Apply a unified diff to original_text and return the updated text.

        This implementation supports patches for a single file with one or more
        hunks, of the form typically produced by difflib.unified_diff. It
        ignores 'diff --git', 'index', and file header lines, and processes
        only hunk headers and +/-/space lines.
        '''
        orig_lines = original_text.splitlines(keepends=True)
        new_lines: list[str] = []

        orig_idx = 0

        hunk_header_re = re.compile(
            r'^@@ -(?P<old_start>\d+)(?:,(?P<old_len>\d+))? ' 
            r'\+(?P<new_start>\d+)(?:,(?P<new_len>\d+))? @@'
        )

        in_hunk = False

        for line in patch_text.splitlines(keepends=True):
            if line.startswith('diff --git') or line.startswith('index '):
                # Ignore Git metadata lines.
                continue
            if line.startswith('--- ') or line.startswith('+++ '):
                # Ignore file header lines; we assume the caller passes `path`.
                continue

            m = hunk_header_re.match(line)
            if m:
                in_hunk = True
                old_start = int(m.group('old_start'))
                # Copy any untouched lines before this hunk.
                target_idx = max(0, old_start - 1)
                if target_idx < orig_idx:
                    raise GitHubAPIError('Patch hunk moves backwards in the file')
                while orig_idx < target_idx and orig_idx < len(orig_lines):
                    new_lines.append(orig_lines[orig_idx])
                    orig_idx += 1
                continue

            if not in_hunk:
                # Skip any preamble before the first hunk.
                continue

            prefix = line[:1]
            content = line[1:]

            if prefix == ' ':
                # Context line: must match original; copy from original.
                if orig_idx >= len(orig_lines):
                    raise GitHubAPIError('Patch context extends beyond end of file')
                if orig_lines[orig_idx] != content:
                    raise GitHubAPIError('Patch context does not match original text')
                new_lines.append(orig_lines[orig_idx])
                orig_idx += 1
            elif prefix == '-':
                # Deletion line: skip the corresponding original line.
                if orig_idx >= len(orig_lines):
                    raise GitHubAPIError('Patch deletion extends beyond end of file')
                if orig_lines[orig_idx] != content:
                    raise GitHubAPIError('Patch deletion does not match original text')
                orig_idx += 1
            elif prefix == '+':
                # Addition line: insert new content.
                new_lines.append(content)
            elif prefix in {'@', '#'}:
                # Unexpected hunk or comment-style line inside a hunk.
                raise GitHubAPIError(f'Unsupported patch line inside hunk: {line!r}')
            else:
                raise GitHubAPIError(f'Unsupported patch line prefix: {prefix!r}')

        # Append any remaining original lines that were not part of a hunk.
        while orig_idx < len(orig_lines):
            new_lines.append(orig_lines[orig_idx])
            orig_idx += 1

        return ''.join(new_lines)

    # Validate that the patch only touches this path.
    header_paths = _extract_paths_from_patch(patch)
    if header_paths:
        if len(header_paths) > 1:
            raise GitHubAPIError(
                'apply_patch_and_commit only supports patches for a single path; '
                f'found: {sorted(header_paths)}'
            )
        header_path = next(iter(header_paths))
        if header_path != path:
            raise GitHubAPIError(
                'Patch path mismatch: tool was called with path='
                f'{path!r} but patch headers refer to {header_path!r}'
            )

    # 1) Read current file from GitHub on the target branch. Treat a 404 as a new file.
    is_new_file = False
    try:
        decoded = await _decode_github_content(full_name, path, effective_branch)
        old_text = decoded.get('text')
        if not isinstance(old_text, str):
            raise GitHubAPIError('Decoded content is not text')
        sha_before = _extract_sha(decoded)
    except GitHubAPIError as exc:
        msg = str(exc)
        if '404' in msg and '/contents/' in msg:
            is_new_file = True
            old_text = ''
            sha_before = None
        else:
            raise

    # 2) Apply the patch to get the updated text.
    try:
        new_text = _apply_unified_diff_to_text(old_text, patch)
    except GitHubAPIError:
        raise
    except Exception as exc:  # pragma: no cover - defensive wrapper
        raise GitHubAPIError(f'Failed to apply patch to {path}: {exc}') from exc

    body_bytes = new_text.encode('utf-8')
    if message is not None:
        commit_message = message
    else:
        default_action = 'Create' if is_new_file else 'Update'
        commit_message = f'{default_action} {path} via patch'

    # 3) Commit the new content via the GitHub Contents API.
    commit_result = await _perform_github_commit(
        full_name=full_name,
        path=path,
        message=commit_message,
        body_bytes=body_bytes,
        branch=effective_branch,
        sha=sha_before,
    )

    # 4) Verify by reading the file again from the same branch.
    verified = await _decode_github_content(full_name, path, effective_branch)
    new_text_verified = verified.get('text')
    sha_after = _extract_sha(verified)

    result: Dict[str, Any] = {
        'status': 'committed',
        'full_name': full_name,
        'path': path,
        'branch': effective_branch,
        'message': commit_message,
        'commit': commit_result,
        'verification': {
            'sha_before': sha_before,
            'sha_after': sha_after,
            'html_url': verified.get('html_url'),
        },
    }

    # Optional: recompute a unified diff between old and verified new text.
    if return_diff:
        diff_iter = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            (new_text_verified or '').splitlines(keepends=True),
            fromfile=f'a/{path}',
            tofile=f'b/{path}',
            n=3,
        )
        result['diff'] = ''.join(diff_iter)

    return result


middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

# SSE endpoint at /sse plus POST /messages handled by FastMCP internally.
app = mcp.http_app(path="/sse", middleware=middleware, transport="sse")

HOME_MESSAGE = (
    "GitHub MCP server is running. Connect your ChatGPT MCP client to /sse "
    "(POST back to /messages) and use /healthz for health checks.\n"
)


@mcp.custom_route("/", methods=["GET"])
async def homepage(request: Request) -> PlainTextResponse:
    return PlainTextResponse(HOME_MESSAGE)


def _build_health_payload() -> Dict[str, Any]:
    # Construct a small JSON health payload for the HTTP health check endpoint.
    #
    # Keeping this logic in a helper keeps /healthz aligned with the controller
    # configuration and exposes a minimal view of in-process metrics without
    # changing any structured log shapes validated elsewhere.

    now = time.time()
    uptime_seconds = max(0.0, now - SERVER_START_TIME)

    return {
        "status": "ok",
        "uptime_seconds": uptime_seconds,
        "github_token_present": bool(GITHUB_PAT),
        "controller": {
            "repo": CONTROLLER_REPO,
            "default_branch": CONTROLLER_DEFAULT_BRANCH,
        },
        "metrics": _metrics_snapshot(),
    }


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    # Lightweight JSON health endpoint with metrics summary.
    #
    # The body is intentionally small: a status flag, uptime, basic controller
    # configuration, and a compact metrics snapshot suitable for logs or external
    # polling.

    payload = _build_health_payload()
    return JSONResponse(payload)


async def _shutdown_clients() -> None:
    if _http_client_github is not None:
        await _http_client_github.aclose()
    if _http_client_external is not None:
        await _http_client_external.aclose()


app.add_event_handler("shutdown", _shutdown_clients)


@mcp_tool(
    write_action=False,
    description=(
        "Return a compact overview of a pull request, including files and CI status."
    ),
)
async def get_pr_overview(full_name: str, pull_number: int) -> Dict[str, Any]:
    # Summarize a pull request so I can decide what to do next.
    #
    # This helper is read-only and safe to call before any write actions.

    pr_resp = await fetch_pr(full_name, pull_number)
    pr_json = pr_resp.get("json") or {}
    if not isinstance(pr_json, dict):
        pr_json = {}

    def _get_user(raw: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(raw, dict):
            return None
        login = raw.get("login")
        if not isinstance(login, str):
            return None
        return {"login": login, "html_url": raw.get("html_url")}

    pr_summary: Dict[str, Any] = {
        "number": pr_json.get("number"),
        "title": pr_json.get("title"),
        "state": pr_json.get("state"),
        "draft": pr_json.get("draft"),
        "merged": pr_json.get("merged"),
        "html_url": pr_json.get("html_url"),
        "user": _get_user(pr_json.get("user")),
        "created_at": pr_json.get("created_at"),
        "updated_at": pr_json.get("updated_at"),
        "closed_at": pr_json.get("closed_at"),
        "merged_at": pr_json.get("merged_at"),
    }

    files: List[Dict[str, Any]] = []
    try:
        files_resp = await list_pr_changed_filenames(full_name, pull_number, per_page=100)
        files_json = files_resp.get("json") or []
        if isinstance(files_json, list):
            for f in files_json:
                if not isinstance(f, dict):
                    continue
                files.append(
                    {
                        "filename": f.get("filename"),
                        "status": f.get("status"),
                        "additions": f.get("additions"),
                        "deletions": f.get("deletions"),
                        "changes": f.get("changes"),
                    }
                )
    except Exception:
        files = []

    status_checks: Optional[Dict[str, Any]] = None
    head = pr_json.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if isinstance(head_sha, str):
        try:
            status_resp = await get_commit_combined_status(full_name, head_sha)
            status_checks = status_resp.get("json") or {}
        except Exception:
            status_checks = None

    workflow_runs: List[Dict[str, Any]] = []
    head_ref = head.get("ref") if isinstance(head, dict) else None
    if isinstance(head_ref, str):
        try:
            runs_resp = await list_workflow_runs(
                full_name,
                branch=head_ref,
                per_page=5,
                page=1,
            )
            runs_json = runs_resp.get("json") or {}
            raw_runs = runs_json.get("workflow_runs", []) if isinstance(runs_json, dict) else []
            for run in raw_runs:
                if not isinstance(run, dict):
                    continue
                workflow_runs.append(
                    {
                        "id": run.get("id"),
                        "name": run.get("name"),
                        "event": run.get("event"),
                        "status": run.get("status"),
                        "conclusion": run.get("conclusion"),
                        "head_branch": run.get("head_branch"),
                        "head_sha": run.get("head_sha"),
                        "html_url": run.get("html_url"),
                        "created_at": run.get("created_at"),
                        "updated_at": run.get("updated_at"),
                    }
                )
        except Exception:
            workflow_runs = []

    return {
        "repository": full_name,
        "pull_number": pull_number,
        "pr": pr_summary,
        "files": files,
        "status_checks": status_checks,
        "workflow_runs": workflow_runs,
    }


@mcp_tool(
    write_action=False,
    description="Return recent pull requests associated with a branch, grouped by state.",
    tags=["github", "read", "navigation", "prs"],
)
async def recent_prs_for_branch(
    full_name: str,
    branch: str,
    include_closed: bool = False,
    per_page_open: int = 20,
    per_page_closed: int = 5,
) -> Dict[str, Any]:
    # Return recent pull requests whose head matches the given branch.
    #
    # This is a composite navigation helper built on top of list_pull_requests.
    # It groups results into open and (optionally) closed sets so assistants can
    # find the PR(s) tied to a feature branch without guessing numbers.
    if not full_name or "/" not in full_name:
        raise ValueError("full_name must be of the form 'owner/repo'")
    if not branch:
        raise ValueError("branch must be a non-empty string")

    owner, _repo = full_name.split("/", 1)
    head_filter = f"{owner}:{branch}"

    open_resp = await list_pull_requests(
        full_name=full_name,
        state="open",
        head=head_filter,
        per_page=per_page_open,
        page=1,
    )
    open_raw = open_resp.get("json") or []
    open_prs = [
        _normalize_pr_payload(pr)
        for pr in open_raw
        if isinstance(pr, dict)
    ]
    open_prs = [pr for pr in open_prs if pr is not None]

    closed_prs: List[Dict[str, Any]] = []
    if include_closed:
        closed_resp = await list_pull_requests(
            full_name=full_name,
            state="closed",
            head=head_filter,
            per_page=per_page_closed,
            page=1,
        )
        closed_raw = closed_resp.get("json") or []
        closed_prs = [
            _normalize_pr_payload(pr)
            for pr in closed_raw
            if isinstance(pr, dict)
        ]
        closed_prs = [pr for pr in closed_prs if pr is not None]

    return {
        "full_name": full_name,
        "branch": branch,
        "head_filter": head_filter,
        "open": open_prs,
        "closed": closed_prs,
    }
