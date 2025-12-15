"""GitHub MCP server exposing connector-friendly tools and workflows.

This module is the entry point for the GitHub Model Context Protocol server
used by ChatGPT connectors. It lists the tools, arguments, and behaviors in a
single place so an assistant can decide how to interact with the server without
being pushed toward a particular working style. See ``docs/WORKFLOWS.md`` and ``docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md``
for optional, non-binding examples of how the tools can fit together.
"""

import asyncio
import base64
import json
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Literal
import httpx  # noqa: F401

import github_mcp.server as server  # noqa: F401
import github_mcp.tools_workspace as tools_workspace  # noqa: F401
from github_mcp import http_clients as _http_clients  # noqa: F401
from github_mcp.config import (
    BASE_LOGGER,  # noqa: F401
    FETCH_FILES_CONCURRENCY,
    FILE_CACHE_MAX_BYTES,  # noqa: F401
    FILE_CACHE_MAX_ENTRIES,  # noqa: F401
    GIT_AUTHOR_EMAIL,
    GIT_AUTHOR_NAME,
    GIT_COMMITTER_EMAIL,
    GIT_COMMITTER_NAME,
    GITHUB_API_BASE,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    MAX_CONCURRENCY,
    TOOL_STDERR_MAX_CHARS,  # noqa: F401
    TOOL_STDIO_COMBINED_MAX_CHARS,  # noqa: F401
    TOOL_STDOUT_MAX_CHARS,  # noqa: F401
    WORKSPACE_BASE_DIR,  # noqa: F401
    ERROR_LOG_HANDLER,
    ERROR_LOG_CAPACITY,
)
from github_mcp.exceptions import (
    GitHubAPIError,  # noqa: F401
    GitHubAuthError,
    GitHubRateLimitError,  # noqa: F401
    WriteNotAuthorizedError,  # noqa: F401
)
from github_mcp.github_content import (
    _decode_github_content,
    _load_body_from_content_url,
    _perform_github_commit,
    _resolve_file_sha,
)
from github_mcp.file_cache import (
    bulk_get_cached,
    cache_payload,
    cache_stats,
    clear_cache,
)
from github_mcp.http_clients import (
    _external_client_instance,
    _get_concurrency_semaphore,  # noqa: F401
    _github_client_instance,
    _get_github_token,  # noqa: F401
)
from github_mcp.metrics import (
    _METRICS,  # noqa: F401
    _metrics_snapshot,  # noqa: F401
    _reset_metrics_for_tests,  # noqa: F401
)
from github_mcp.server import (
    _REGISTERED_MCP_TOOLS,  # noqa: F401
    CONTROLLER_DEFAULT_BRANCH,
    CONTROLLER_REPO,
    _ensure_write_allowed,
    _github_request,
    _structured_tool_error,
    mcp_tool,
    register_extra_tools_if_available,
    COMPACT_METADATA_DEFAULT,
    _find_registered_tool,
    _normalize_input_schema,
)
from github_mcp.tools_workspace import commit_workspace, ensure_workspace_clone  # noqa: F401
from github_mcp.utils import (
    REPO_DEFAULTS,
    _effective_ref_for_repo,
    _normalize_repo_path,
    _with_numbered_lines,
    _normalize_write_context,
    normalize_args,
)
from github_mcp.workspace import (
    _clone_repo,  # noqa: F401
    _prepare_temp_virtualenv,  # noqa: F401
    _run_shell,  # noqa: F401
    _workspace_path,  # noqa: F401
)
from starlette.requests import Request
from starlette.responses import JSONResponse



# Exposed for tests that monkeypatch the external HTTP client used for sandbox: URLs.
_http_client_external: httpx.AsyncClient | None = None

LOGGER = BASE_LOGGER.getChild("main")

# Keep selected symbols in main for tests/backwards-compat and for impl modules.
_EXPORT_COMPAT = (
    COMPACT_METADATA_DEFAULT,
    _find_registered_tool,
    _normalize_input_schema,
    normalize_args,
)


async def _perform_github_commit_and_refresh_workspace(
    *,
    full_name: str,
    path: str,
    message: str,
    branch: str,
    body_bytes: bytes,
    sha: Optional[str],
) -> Dict[str, Any]:
    """Perform a Contents API commit and then refresh the workspace clone.

    This keeps the long-lived workspace clone in sync with the branch when
    writes happen directly via the GitHub Contents API. Workspace refresh
    failures are logged but never fail the commit itself.
    """

    commit_result = await _perform_github_commit(
        full_name=full_name,
        path=path,
        message=message,
        body_bytes=body_bytes,
        branch=branch,
        sha=sha,
    )

    try:
        # Best-effort: do not break commits if workspace refresh fails.
        await ensure_workspace_clone(
            full_name=full_name,
            ref=branch,
            reset=True,
        )
    except Exception as exc:  # pragma: no cover - defensive logging only
        LOGGER.debug(
            "Failed to refresh workspace after commit",
            extra={
                "full_name": full_name,
                "branch": branch,
                "error": str(exc),
            },
        )

    return commit_result


def __getattr__(name: str):
    if name == "WRITE_ALLOWED":
        return server.WRITE_ALLOWED
    raise AttributeError(name)


# Recalculate write gate on import to honor updated environment variables when
# ``main`` is reloaded in tests.
server.WRITE_ALLOWED = server._env_flag("GITHUB_MCP_AUTO_APPROVE", False)

register_extra_tools_if_available()

# Expose an ASGI app for hosting via uvicorn/Render. The FastMCP server lazily
# constructs a Starlette application through ``http_app``; we create it once at
# import time so ``uvicorn main:app`` works as expected.
#
# Force the SSE transport so the controller serves ``/sse`` again. FastMCP
# 2.14 defaults to the streamable HTTP transport, which removed the SSE route
# and caused the public endpoint to return ``404 Not Found``. Using the SSE
# transport keeps the documented ``/sse`` path working for existing clients.
app = server.mcp.http_app(path="/sse", transport="sse")


def _serialize_actions_for_compatibility() -> list[dict[str, Any]]:
    """Expose a stable actions listing for clients expecting /v1/actions.

    The FastMCP server only exposes its MCP transport at ``/mcp`` by default.
    Some clients (including the ChatGPT UI) attempt to refresh available
    Actions using the OpenAI Actions-style ``/v1/actions`` endpoint. Provide a
    lightweight JSON response that mirrors the MCP tool surface so those
    clients receive a graceful payload instead of a 404.
    """

    actions: list[dict[str, Any]] = []
    for tool, _func in server._REGISTERED_MCP_TOOLS:
        schema = server._normalize_input_schema(tool)
        actions.append(
            {
                "name": tool.name,
                "display_name": getattr(tool, "title", None) or tool.name,
                "description": tool.description,
                "parameters": schema or {"type": "object", "properties": {}},
                "annotations": getattr(tool, "annotations", None).model_dump() if getattr(tool, "annotations", None) else None,
            }
        )

    return actions


async def _actions_compatibility_endpoint(_: Request) -> JSONResponse:
    return JSONResponse({"actions": _serialize_actions_for_compatibility()})


app.add_route("/v1/actions", _actions_compatibility_endpoint, methods=["GET"])
app.add_route("/actions", _actions_compatibility_endpoint, methods=["GET"])


def _cache_file_result(
    *, full_name: str, path: str, ref: str, decoded: Dict[str, Any]
) -> Dict[str, Any]:
    normalized_path = _normalize_repo_path(path)
    effective_ref = _effective_ref_for_repo(full_name, ref)
    return cache_payload(
        full_name=full_name,
        ref=effective_ref,
        path=normalized_path,
        decoded=decoded,
    )


def _reset_file_cache_for_tests() -> None:
    clear_cache()


async def terminal_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
) -> Dict[str, Any]:
    """Run a shell command in the persistent repo workspace (terminal gateway).

    This is a thin wrapper around github_mcp.tools_workspace.terminal_command.
    """
    return await tools_workspace.terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )


async def run_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
) -> Dict[str, Any]:
    """Thin wrapper around github_mcp.tools_workspace.terminal_command (via run_command alias).

    Tests import run_command from main so this helper forwards to the
    workspace tool while still allowing monkeypatching of internal
    dependencies like _clone_repo and _run_shell on the main module.
    """
    return await tools_workspace.run_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )


async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
) -> Dict[str, Any]:
    """Forward run_tests calls to the workspace helper for test surfaces."""

    return await tools_workspace.run_tests(
        full_name=full_name,
        ref=ref,
        test_command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )


async def commit_workspace_files(
    full_name: str,
    files: List[str],
    ref: str = "main",
    message: str = "Commit selected workspace changes",
    push: bool = True,
) -> Dict[str, Any]:
    """Forward commit_workspace_files calls to the workspace tool.

    Keeping this shim in main preserves the test-oriented API surface
    without duplicating implementation details.
    """
    return await tools_workspace.commit_workspace_files(
        full_name=full_name,
        files=files,
        ref=ref,
        message=message,
        push=push,
    )


@mcp_tool(write_action=False)
def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    """Allow or block tools marked write_action=True for this server."""

    server.WRITE_ALLOWED = bool(approved)
    return {"write_allowed": server.WRITE_ALLOWED}


# ------------------------------------------------------------------------------
# Read-only tools


@server.mcp_tool(write_action=False)
def get_recent_tool_events(limit: int = 50, include_success: bool = True) -> Dict[str, Any]:
    """Return recent tool-call events captured in-memory by the server wrappers."""
    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 50
    limit_int = max(1, min(200, limit_int))
    events = list(getattr(server, "RECENT_TOOL_EVENTS", []))
    if not include_success:
        events = [e for e in events if e.get("event") != "tool_recent_ok"]
    events = list(reversed(events))[:limit_int]

    # Plain-language summaries for UI surfaces.
    narrative = []
    for e in events:
        msg = e.get("user_message")
        if not msg:
            tool = e.get("tool_name") or "tool"
            ev = e.get("event") or "event"
            repo = e.get("repo") or "-"
            ref = e.get("ref") or "-"
            dur = e.get("duration_ms")
            loc = f"{repo}@{ref}" if ref not in {None, "", "-"} else repo
            if ev == "tool_recent_start":
                msg = f"Starting {tool} on {loc}."
            elif ev == "tool_recent_ok":
                msg = f"Finished {tool} on {loc}{(' in %sms' % dur) if isinstance(dur, int) else ''}."
            else:
                msg = f"{tool} event {ev} on {loc}."
        narrative.append(msg)

    transcript = "\n".join(narrative)

    return {
        "limit": limit_int,
        "include_success": include_success,
        "events": events,
        "narrative": narrative,
        "transcript": transcript,
    }


@server.mcp_tool(write_action=False)
def get_recent_server_errors(limit: int = 50) -> Dict[str, Any]:
    """Return recent server-side error logs for failed MCP tool calls.

    This surfaces the underlying MCP server error records so assistants can
    debug misinputs instead of re-looping blindly.
    """

    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 50
    limit_int = max(1, min(ERROR_LOG_CAPACITY, limit_int))

    records = getattr(ERROR_LOG_HANDLER, "records", [])
    records = list(reversed(records))[:limit_int]

    return {
        "limit": limit_int,
        "capacity": ERROR_LOG_CAPACITY,
        "errors": records,
    }


# ------------------------------------------------------------------------------

@mcp_tool(write_action=False)
async def get_server_config() -> Dict[str, Any]:
    """Return a safe summary of MCP connector and runtime settings."""

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
    description="Validate a JSON string and return a normalized form.",
    tags=["meta", "json", "validation"],
)
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


@mcp_tool(write_action=False)
async def get_repo_defaults(
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Return default configuration for a GitHub repository."""

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
    """Check GitHub-related environment settings and report problems."""
    from github_mcp.main_tools.env import validate_environment as _impl
    return await _impl()



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
    base = base_branch or defaults_payload.get("default_branch") or CONTROLLER_DEFAULT_BRANCH

    import uuid

    branch = f"mcp-pr-smoke-{uuid.uuid4().hex[:8]}"

    await ensure_branch(full_name=repo, branch=branch, from_ref=base)

    path = "mcp_pr_smoke_test.txt"
    normalized_path = _normalize_repo_path(path)
    content = f"MCP PR smoke test branch {branch}.\n"

    await apply_text_update_and_commit(
        full_name=repo,
        path=normalized_path,
        updated_content=content,
        branch=branch,
        message=f"MCP PR smoke test on {branch}",
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


@mcp_tool(write_action=True)
async def create_repository(
    name: str,
    owner: Optional[str] = None,
    owner_type: Literal["auto", "user", "org"] = "auto",
    description: Optional[str] = None,
    homepage: Optional[str] = None,
    visibility: Optional[Literal["public", "private", "internal"]] = None,
    private: Optional[bool] = None,
    auto_init: bool = True,
    gitignore_template: Optional[str] = None,
    license_template: Optional[str] = None,
    is_template: bool = False,
    has_issues: bool = True,
    has_projects: Optional[bool] = None,
    has_wiki: bool = True,
    has_discussions: Optional[bool] = None,
    team_id: Optional[int] = None,
    security_and_analysis: Optional[Dict[str, Any]] = None,
    template_full_name: Optional[str] = None,
    include_all_branches: bool = False,
    topics: Optional[List[str]] = None,
    create_payload_overrides: Optional[Dict[str, Any]] = None,
    update_payload_overrides: Optional[Dict[str, Any]] = None,
    clone_to_workspace: bool = False,
    clone_ref: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new GitHub repository for the authenticated user or an organization.

    Designed to match GitHub's "New repository" UI with a safe escape hatch:

    - Use first-class params for common fields.
    - Use create_payload_overrides and update_payload_overrides to pass any
      additional GitHub REST fields without waiting for server updates.

    Template-based creation is supported via template_full_name using:
    POST /repos/{template_owner}/{template_repo}/generate
    """

    steps: List[str] = []
    warnings: List[str] = []

    try:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a non-empty string")
        name = name.strip()

        if "/" in name or name.endswith(".git"):
            raise ValueError("name must not contain '/' and must not end with '.git'")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", name):
            raise ValueError(
                "name must match [A-Za-z0-9][A-Za-z0-9_.-]{0,99} (max 100 chars)"
            )

        if visibility is not None and private is not None:
            inferred_private = visibility != "public"
            if inferred_private != private:
                raise ValueError("visibility and private disagree")

        if visibility is not None:
            effective_private = visibility != "public"
        elif private is not None:
            effective_private = bool(private)
        else:
            effective_private = False

        target_owner = owner.strip() if isinstance(owner, str) and owner.strip() else None
        authenticated_login: Optional[str] = None

        # Resolve the authenticated user (needed for auto owner and template generation).
        if owner_type != "org" or template_full_name:
            user = await _github_request("GET", "/user")
            if isinstance(user.get("json"), dict):
                authenticated_login = user["json"].get("login")
            if not target_owner:
                target_owner = authenticated_login

        if owner_type == "org" and not target_owner:
            raise ValueError("owner is required when owner_type='org'")

        use_org_endpoint = False
        if owner_type == "org":
            use_org_endpoint = True
        elif owner_type == "user":
            use_org_endpoint = False
            if target_owner and authenticated_login and target_owner != authenticated_login:
                warnings.append(
                    f"owner '{target_owner}' differs from authenticated user '{authenticated_login}'; using user endpoint"
                )
        else:
            # auto: if caller provided an owner different from auth login, assume org.
            if target_owner and authenticated_login and target_owner != authenticated_login:
                use_org_endpoint = True

        create_target_desc = (
            f"{target_owner}/{name}" if target_owner else f"(authenticated-user)/{name}"
        )
        _ensure_write_allowed(f"create repository {create_target_desc}")

        def _apply_overrides(
            base: Dict[str, Any], overrides: Optional[Dict[str, Any]]
        ) -> Dict[str, Any]:
            if overrides and isinstance(overrides, dict):
                base.update(overrides)
            return base

        created_resp: Dict[str, Any]
        create_payload: Dict[str, Any]

        if template_full_name:
            if not isinstance(template_full_name, str) or "/" not in template_full_name:
                raise ValueError("template_full_name must look like 'owner/repo'")
            template_full_name = template_full_name.strip()

            steps.append(
                f"Creating repository from template {template_full_name} as {create_target_desc}."
            )
            create_payload = {
                "owner": target_owner,
                "name": name,
                "description": description,
                "private": effective_private,
                "include_all_branches": bool(include_all_branches),
            }
            create_payload = _apply_overrides(create_payload, create_payload_overrides)
            created_resp = await _github_request(
                "POST", f"/repos/{template_full_name}/generate", json_body=create_payload
            )
        else:
            endpoint = "/user/repos"
            if use_org_endpoint:
                endpoint = f"/orgs/{target_owner}/repos"

            steps.append(f"Creating repository {create_target_desc} via {endpoint}.")
            create_payload = {
                "name": name,
                "description": description,
                "homepage": homepage,
                "private": effective_private,
                "auto_init": bool(auto_init),
                "is_template": bool(is_template),
                "has_issues": bool(has_issues),
                "has_wiki": bool(has_wiki),
            }
            if visibility is not None:
                create_payload["visibility"] = visibility
            if gitignore_template:
                create_payload["gitignore_template"] = gitignore_template
            if license_template:
                create_payload["license_template"] = license_template
            if has_projects is not None:
                create_payload["has_projects"] = bool(has_projects)
            if has_discussions is not None:
                create_payload["has_discussions"] = bool(has_discussions)
            if team_id is not None:
                create_payload["team_id"] = int(team_id)
            if security_and_analysis is not None:
                create_payload["security_and_analysis"] = security_and_analysis

            create_payload = _apply_overrides(create_payload, create_payload_overrides)
            created_resp = await _github_request("POST", endpoint, json_body=create_payload)

        repo_json = created_resp.get("json") if isinstance(created_resp, dict) else None
        full_name = repo_json.get("full_name") if isinstance(repo_json, dict) else None
        if not isinstance(full_name, str) or not full_name:
            if target_owner:
                full_name = f"{target_owner}/{name}"

        updated_resp = None
        if update_payload_overrides and full_name:
            steps.append(f"Applying post-create settings to {full_name}.")
            updated_resp = await _github_request(
                "PATCH", f"/repos/{full_name}", json_body=dict(update_payload_overrides)
            )

        topics_resp = None
        if topics and full_name:
            cleaned = [t.strip() for t in topics if isinstance(t, str) and t.strip()]
            if cleaned:
                steps.append(f"Setting topics on {full_name}: {', '.join(cleaned)}.")
                topics_resp = await _github_request(
                    "PUT",
                    f"/repos/{full_name}/topics",
                    json_body={"names": cleaned},
                    headers={"Accept": "application/vnd.github+json"},
                )

        workspace_dir = None
        if clone_to_workspace and full_name:
            steps.append(f"Cloning {full_name}@{clone_ref or 'default'} into workspace.")
            workspace_dir = await _clone_repo(full_name, ref=clone_ref)

        return {
            "full_name": full_name,
            "repo": repo_json,
            "created": created_resp,
            "create_payload": create_payload,
            "updated": updated_resp,
            "topics": topics_resp,
            "workspace_dir": workspace_dir,
            "steps": steps,
            "warnings": warnings,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="create_repository")


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
    """Get metadata for a pull request."""

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
    from github_mcp.main_tools.introspection import list_write_tools as _impl
    return _impl()



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
        if "404" in msg:
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
    decoded = await _decode_github_content(full_name, path, ref)
    _cache_file_result(full_name=full_name, path=path, ref=ref, decoded=decoded)
    return decoded


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
        normalized_path = _normalize_repo_path(p)
        async with sem:
            try:
                decoded = await _decode_github_content(full_name, normalized_path, ref)
                cached = _cache_file_result(
                    full_name=full_name,
                    path=normalized_path,
                    ref=ref,
                    decoded=decoded,
                )
                results[p] = cached
            except Exception as e:
                # Use a consistent error envelope so controllers can rely on structure.
                results[p] = _structured_tool_error(
                    str(e),
                    context="fetch_files",
                    path=p,
                )

    await asyncio.gather(*[_fetch_single(p) for p in paths])
    return {"files": results}


@mcp_tool(
    write_action=False,
    description=(
        "Return cached file payloads for a repository/ref without re-fetching "
        "from GitHub. Entries persist for the lifetime of the server process "
        "until evicted by size or entry caps."
    ),
    tags=["github", "cache", "files"],
)
async def get_cached_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
) -> Dict[str, Any]:
    """Return cached file entries and list any missing paths."""

    effective_ref = _effective_ref_for_repo(full_name, ref)
    normalized_paths = [_normalize_repo_path(p) for p in paths]
    cached = bulk_get_cached(full_name, effective_ref, normalized_paths)
    missing = [p for p in normalized_paths if p not in cached]

    return {
        "full_name": full_name,
        "ref": effective_ref,
        "files": cached,
        "missing": missing,
        "cache": cache_stats(),
    }


@mcp_tool(
    write_action=False,
    description=(
        "Fetch one or more files and persist them in the server-side cache so "
        "assistants can recall them without repeating GitHub reads. Use "
        "refresh=true to bypass existing cache entries."
    ),
    tags=["github", "cache", "files"],
)
async def cache_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
    refresh: bool = False,
) -> Dict[str, Any]:
    """Fetch files and store them in the in-process cache."""

    results: Dict[str, Any] = {}
    effective_ref = _effective_ref_for_repo(full_name, ref)
    normalized_paths = [_normalize_repo_path(p) for p in paths]
    cached_existing: Dict[str, Any] = {}
    if not refresh:
        cached_existing = bulk_get_cached(full_name, effective_ref, normalized_paths)

    sem = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def _cache_single(p: str) -> None:
        async with sem:
            if not refresh and p in cached_existing:
                results[p] = {**cached_existing[p], "cached": True}
                return

            decoded = await _decode_github_content(full_name, p, effective_ref)
            cached = cache_payload(
                full_name=full_name,
                ref=effective_ref,
                path=p,
                decoded=decoded,
            )
            results[p] = {**cached, "cached": False}

    await asyncio.gather(*[_cache_single(p) for p in normalized_paths])

    return {
        "full_name": full_name,
        "ref": effective_ref,
        "files": results,
        "cache": cache_stats(),
    }


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

        normalized_path = _normalize_repo_path(path)

        filtered_entries.append(
            {
                "path": normalized_path,
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
    async with _get_concurrency_semaphore():
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
    search_type: Literal["code", "repositories", "issues", "commits", "users"] = "code",
    per_page: int = 30,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[Literal["asc", "desc"]] = None,
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


def _decode_zipped_job_logs(content: bytes) -> str:
    """Decode a zipped GitHub Actions job logs payload into a readable string.

    Returns an empty string for invalid zip payloads. For valid zip files,
    entries are sorted by filename and combined with section headers:

        [file.txt]
<contents>
    """

    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zip_file:
            names = sorted(zip_file.namelist())
            parts: list[str] = []
            for name in names:
                try:
                    raw = zip_file.read(name)
                except Exception:
                    continue
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    text = raw.decode("utf-8", errors="replace")
                parts.append(f"[{name}]\n{text}")
            return "\n\n".join(parts)
    except Exception:
        return ""


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
    from github_mcp.main_tools.workflows import list_workflow_runs as _impl
    return await _impl(full_name=full_name, branch=branch, status=status, event=event, per_page=per_page, page=page)



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
    from github_mcp.main_tools.workflows import list_recent_failures as _impl
    return await _impl(full_name=full_name, branch=branch, limit=limit)



@mcp_tool(
    write_action=False,
    description=(
        "List available MCP tools with basic read/write metadata. "
        "Use describe_tool (or list_all_actions with include_parameters=true) when you need full schemas."
    ),
)
async def list_tools(
    only_write: bool = False,
    only_read: bool = False,
    name_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Lightweight tool catalog.

    Args:
        only_write: If True, return only write-tagged tools.
        only_read: If True, return only read-tagged tools.
        name_prefix: Optional prefix filter for tool names.

    Notes:
        - For schema/args: call describe_tool(include_parameters=true) and validate_tool_args.
        - If you see tool-call JSON/schema errors: stop guessing and re-read the schema.
    """

    if only_write and only_read:
        raise ValueError("only_write and only_read cannot both be true")

    catalog = list_all_actions(include_parameters=False, compact=True)
    tools = []
    for entry in catalog.get("tools", []) or []:
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        if name_prefix and not name.startswith(name_prefix):
            continue

        write_action = bool(entry.get("write_action"))
        if only_write and not write_action:
            continue
        if only_read and write_action:
            continue

        tools.append(
            {
                "name": name,
                "write_action": write_action,
                "operation": entry.get("operation"),
                "risk_level": entry.get("risk_level"),
                "auto_approved": bool(entry.get("auto_approved")),
            }
        )

    tools.sort(key=lambda t: t["name"])
    return {
        "write_actions_enabled": server.WRITE_ALLOWED,
        "tools": tools,
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
            set), shorten descriptions and omit tag metadata to keep responses
            compact.
    """
    from github_mcp.main_tools.introspection import list_all_actions as _impl
    return _impl(include_parameters=include_parameters, compact=compact)



@mcp_tool(
    write_action=False,
    description=(
        "Return metadata and optional schema for one or more tools. "
        "Prefer this over manually scanning list_all_actions in long sessions."
    ),
)
async def describe_tool(
    name: Optional[str] = None,
    names: Optional[List[str]] = None,
    include_parameters: bool = True,
) -> Dict[str, Any]:
    """Inspect one or more registered MCP tools by name.

    This is a convenience wrapper around list_all_actions: it lets callers
    inspect specific tools by name without scanning the entire tool catalog.

    Args:
        name: The MCP tool name (for example, "update_files_and_open_pr").
            For backwards compatibility, this behaves like the legacy
            single-tool describe_tool API.
        names: Optional list of tool names to inspect. When provided, up to
            10 tools are returned in a single call. Duplicates are ignored
            while preserving order.
        include_parameters: When True, include the serialized input schema for
            each tool (equivalent to list_all_actions(include_parameters=True)).
    """
    from github_mcp.main_tools.introspection import describe_tool as _impl
    return await _impl(name=name, names=names, include_parameters=include_parameters)



def _validate_single_tool_args(tool_name: str, args: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate a single candidate payload against a tool's input schema."""
    from github_mcp.main_tools.introspection import _validate_single_tool_args as _impl
    return _impl(tool_name=tool_name, args=args)



@mcp_tool(write_action=False)
async def validate_tool_args(
    tool_name: Optional[str] = None,
    payload: Optional[Mapping[str, Any]] = None,
    tool_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Validate candidate payload(s) against tool input schemas without running them.

    Args:
        tool_name: Name of a single MCP tool to validate. This preserves the
            legacy single-tool validate_tool_args API.
        payload: Candidate arguments object to validate. In batch mode this
            payload is applied to each tool in tool_names.
        tool_names: Optional list of MCP tool names to validate in one call.
            When provided, up to 10 tools are validated using the same payload.
            Duplicates are ignored while preserving order.

    Raises:
        ToolPreflightValidationError: If the branch/path combination fails server-side normalization.

    Returns:
        For single-tool calls, returns the legacy shape:

            {"tool": ..., "valid": bool, "errors": [...], "schema": ...}

        For batch calls (tool_names present), returns a dict with:

            - results: list of per-tool validation results in call order
            - missing_tools: optional list of unknown tool names

        The first entry in results is mirrored at the top level (tool, valid,
        errors, schema) for backwards compatibility with existing callers.
    """
    from github_mcp.main_tools.introspection import validate_tool_args as _impl
    return await _impl(tool_name=tool_name, payload=payload, tool_names=tool_names)




@mcp_tool(write_action=False)
async def get_workflow_run(full_name: str, run_id: int) -> Dict[str, Any]:
    """Retrieve a specific workflow run including timing and conclusion."""
    from github_mcp.main_tools.workflows import get_workflow_run as _impl
    return await _impl(full_name=full_name, run_id=run_id)



@mcp_tool(write_action=False)
async def list_workflow_run_jobs(
    full_name: str,
    run_id: int,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """List jobs within a workflow run, useful for troubleshooting failures."""
    from github_mcp.main_tools.workflows import list_workflow_run_jobs as _impl
    return await _impl(full_name=full_name, run_id=run_id, per_page=per_page, page=page)



@mcp_tool(write_action=False)
async def get_workflow_run_overview(
    full_name: str,
    run_id: int,
    max_jobs: int = 500,
) -> Dict[str, Any]:
    """Summarize a GitHub Actions workflow run for CI triage.

    This helper is read-only and safe to call before any write actions. It
    aggregates run metadata, jobs (with optional pagination up to max_jobs),
    failed jobs, and the longest jobs by duration so assistants can answer
    "what happened in this run?" with a single tool call.
    """
    from github_mcp.main_tools.workflows import get_workflow_run_overview as _impl
    return await _impl(full_name=full_name, run_id=run_id, max_jobs=max_jobs)



@mcp_tool(write_action=False)
async def get_job_logs(full_name: str, job_id: int) -> Dict[str, Any]:
    """Fetch raw logs for a GitHub Actions job without truncation."""
    from github_mcp.main_tools.workflows import get_job_logs as _impl
    return await _impl(full_name=full_name, job_id=job_id)



@mcp_tool(write_action=False)
async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """Poll a workflow run until completion or timeout."""
    from github_mcp.main_tools.workflows import wait_for_workflow_run as _impl
    return await _impl(full_name=full_name, run_id=run_id, timeout_seconds=timeout_seconds, poll_interval_seconds=poll_interval_seconds)



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
            checklist_items.extend(_extract_checklist_items(body, source="comment"))

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
    from github_mcp.main_tools.workflows import trigger_workflow_dispatch as _impl
    return await _impl(full_name=full_name, workflow=workflow, ref=ref, inputs=inputs)



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
    from github_mcp.main_tools.workflows import trigger_and_wait_for_workflow as _impl
    return await _impl(full_name=full_name, workflow=workflow, ref=ref, inputs=inputs, timeout_seconds=timeout_seconds, poll_interval_seconds=poll_interval_seconds)



# ------------------------------------------------------------------------------
# PR / issue management tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
async def list_pull_requests(
    full_name: str,
    state: Literal["open", "closed", "all"] = "open",
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
    merge_method: Literal["merge", "squash", "rebase"] = "squash",
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
    return await _github_request(
        "PUT", f"/repos/{full_name}/pulls/{number}/merge", json_body=payload
    )


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
    state: Optional[Literal["open", "closed"]] = None,
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
    """Normalize get_branch_summary output into a compact shape.

    Diff/compare data has been removed from the server; this helper focuses on PRs
    and CI signals.
    """

    if not isinstance(summary, dict):
        return None

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


# ------------------------------------------------------------------------------
# Branch / commit / PR helpers
# ------------------------------------------------------------------------------



@mcp_tool(write_action=True)
async def create_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """Create a new branch from a base ref.

    This uses the Git refs API. Prefer ``ensure_branch`` when you want an
    idempotent flow.
    """

    _ensure_write_allowed(f"create branch {branch} from {from_ref} in {full_name}")

    branch = branch.strip()
    if not branch:
        raise ValueError("branch must be non-empty")

    # Conservative branch-name validation.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch):
        raise ValueError("branch contains invalid characters")
    if ".." in branch or "@{" in branch:
        raise ValueError("branch contains invalid ref sequence")
    if branch.startswith("/") or branch.endswith("/"):
        raise ValueError("branch must not start or end with '/'")
    if branch.endswith(".lock"):
        raise ValueError("branch must not end with '.lock'")

    base_ref = _effective_ref_for_repo(full_name, from_ref)

    client = _github_client_instance()

    # Resolve base sha.
    base_sha: Optional[str] = None
    async with _get_concurrency_semaphore():
        resp = await client.get(f"/repos/{full_name}/git/ref/heads/{base_ref}")
    if resp.status_code == 200:
        payload = resp.json() if hasattr(resp, "json") else {}
        obj = payload.get("object") if isinstance(payload, dict) else None
        if isinstance(obj, dict):
            base_sha = obj.get("sha")
    elif resp.status_code == 404:
        # Try tags.
        async with _get_concurrency_semaphore():
            tag_resp = await client.get(f"/repos/{full_name}/git/ref/tags/{base_ref}")
        if tag_resp.status_code == 200:
            payload = tag_resp.json() if hasattr(tag_resp, "json") else {}
            obj = payload.get("object") if isinstance(payload, dict) else None
            if isinstance(obj, dict):
                base_sha = obj.get("sha")
    else:
        raise GitHubAPIError(f"GitHub create_branch base ref error {resp.status_code}: {resp.text}")

    # If base_sha still missing, allow direct SHA usage.
    if base_sha is None:
        if re.fullmatch(r"[0-9a-fA-F]{7,40}", from_ref.strip()):
            base_sha = from_ref.strip()
        else:
            raise GitHubAPIError(f"Unable to resolve base ref {from_ref!r} in {full_name}")

    new_ref = f"refs/heads/{branch}"
    body = {"ref": new_ref, "sha": base_sha}

    async with _get_concurrency_semaphore():
        create_resp = await client.post(f"/repos/{full_name}/git/refs", json=body)

    if create_resp.status_code == 201:
        return {"status_code": create_resp.status_code, "json": create_resp.json()}

    # 422 typically means the ref already exists.
    raise GitHubAPIError(f"GitHub create_branch error {create_resp.status_code}: {create_resp.text}")

@mcp_tool(write_action=True)
async def ensure_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """Idempotently ensure a branch exists, creating it from ``from_ref``."""

    _ensure_write_allowed(f"ensure branch {branch} from {from_ref} in {full_name}")
    client = _github_client_instance()
    async with _get_concurrency_semaphore():
        resp = await client.get(f"/repos/{full_name}/git/ref/heads/{branch}")
    if resp.status_code == 404:
        return await create_branch(full_name, branch, from_ref)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub ensure_branch error {resp.status_code}: {resp.text}")
    return {"status_code": resp.status_code, "json": resp.json()}


@mcp_tool(write_action=False)
async def get_branch_summary(full_name: str, branch: str, base: str = "main") -> Dict[str, Any]:
    """Return PRs and latest workflow run for a branch."""

    effective_branch = _effective_ref_for_repo(full_name, branch)
    effective_base = _effective_ref_for_repo(full_name, base)

    # Diff/compare tooling has been removed; branch summary focuses on PRs and CI.
    compare_error: Optional[str] = None

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
        "compare_error": compare_error,
        "open_prs": open_prs,
        "closed_prs": closed_prs,
        "latest_workflow_run": latest_workflow_run,
        "workflow_error": workflow_error,
    }


@mcp_tool(write_action=False)
async def get_latest_branch_status(
    full_name: str, branch: str, base: str = "main"
) -> Dict[str, Any]:
    """Return a normalized, assistant-friendly view of the latest status for a branch.

    This wraps ``get_branch_summary`` and ``_normalize_branch_summary`` so controllers
    and assistants can quickly answer questions like:

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

    Raises:
        ToolPreflightValidationError: If the branch/path combination fails server-side normalization.

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
    from github_mcp.main_tools.dashboard import get_repo_dashboard as _impl
    return await _impl(full_name=full_name, branch=branch)



async def _build_default_pr_body(
    *,
    full_name: str,
    title: str,
    head: str,
    effective_base: str,
    draft: bool,
) -> str:
    """Compose a rich default PR body when the caller omits one.

    This helper intentionally favors robustness over strictness: if any of the
    underlying GitHub lookups fail, it falls back to partial information instead
    of raising and breaking the overall tool call.
    """
    from github_mcp.main_tools.pull_requests import _build_default_pr_body as _impl
    return await _impl(full_name=full_name, title=title, head=head, effective_base=effective_base, draft=draft)



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
    controller repos honor the configured default branch even when callers
    supply a simple base name like "main".
    """
    from github_mcp.main_tools.pull_requests import create_pull_request as _impl
    return await _impl(full_name=full_name, title=title, head=head, base=base, body=body, draft=draft)


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

    If this tool call is blocked upstream by OpenAI, use the workspace flow: `run_command` to create or reuse the PR.
    """
    from github_mcp.main_tools.pull_requests import open_pr_for_existing_branch as _impl
    return await _impl(full_name=full_name, branch=branch, base=base, title=title, body=body, draft=draft)



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
    from github_mcp.main_tools.pull_requests import update_files_and_open_pr as _impl
    return await _impl(full_name=full_name, title=title, files=files, base_branch=base_branch, new_branch=new_branch, body=body, draft=draft)



@mcp_tool(write_action=True)
async def create_file(
    full_name: str,
    path: str,
    content: str,
    *,
    branch: str = "main",
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new text file in a repository after normalizing path and branch.

    This helper performs a lightweight server-side preflight to normalize the
    target branch and repository path before issuing any write to GitHub. The
    call fails if the file already exists on the target branch.

    Args:
        full_name: "owner/repo" string.
        path: Path of the file within the repository (normalized before write).
        content: UTF-8 text content of the new file.
        branch: Branch to commit to (default "main").
        message: Optional commit message; if omitted, a default is derived.

    Raises:
        ToolPreflightValidationError: If the branch/path combination fails server-side normalization.

    Returns:
        A dict with:
            - status: "created"
            - full_name, path, branch
            - message: The commit message used.
            - commit: Raw commit response from GitHub.
            - verification: A dict containing sha_before (always None),
              sha_after and html_url from a fresh read of the file.

    Raises:
        ToolPreflightValidationError: If the branch/path combination fails
            server-side normalization.
    """

    effective_branch, normalized_path = _normalize_write_context(
        full_name=full_name,
        branch=branch,
        path=path,
    )

    _ensure_write_allowed(
        "create_file %s %s" % (full_name, normalized_path),
        target_ref=effective_branch,
    )

    # Ensure the file does not already exist.
    try:
        await _decode_github_content(full_name, normalized_path, effective_branch)
    except GitHubAPIError as exc:
        msg = str(exc)
        if "404" in msg:
            sha_before: Optional[str] = None
        else:
            raise
    else:
        raise GitHubAPIError(
            f"File already exists at {normalized_path} on branch {effective_branch}"
        )

    body_bytes = content.encode("utf-8")
    commit_message = message or f"Create {normalized_path}"

    commit_result = await _perform_github_commit(
        full_name=full_name,
        path=normalized_path,
        message=commit_message,
        body_bytes=body_bytes,
        branch=effective_branch,
        sha=sha_before,
    )

    verified = await _decode_github_content(full_name, normalized_path, effective_branch)
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
        "path": normalized_path,
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
) -> Dict[str, Any]:
    """Apply a text update to a single file on a branch, then verify it.

    This is a lower-level building block for full-file replacement flows:

    1. Read the current file text from GitHub.
    2. Commit the provided updated_content via the Contents API on the target branch.
    3. Re-read the file to verify the new SHA and contents landed.
    4. Commit the full file contents (no patch/diff application).

    It does NOT create a PR; callers are expected to open a PR separately
    (for example using create_pull_request or update_files_and_open_pr) if
    they want reviewable changes.

    Args:
        full_name: "owner/repo" string.
        path: Path of the file within the repository (normalized before write).
        updated_content: New full text for the file (UTF-8).
        branch: Branch to commit to (default "main").
        message: Commit message; if omitted, a simple "Update <path>" is used.

    Raises:
        ToolPreflightValidationError: If the branch/path combination fails server-side normalization.

    Returns:
        A dict with:
            - status: "committed"
            - full_name, path, branch
            - message: commit message used
            - commit: raw GitHub commit API response
            - verification: {sha_before, sha_after, html_url}
    """


    effective_branch, normalized_path = _normalize_write_context(
        full_name=full_name,
        branch=branch,
        path=path,
    )

    _ensure_write_allowed(
        "apply_text_update_and_commit %s %s" % (full_name, normalized_path),
        target_ref=effective_branch,
    )

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
        decoded = await _decode_github_content(full_name, normalized_path, effective_branch)
        _old_text = decoded.get("text")
        if not isinstance(_old_text, str):
            raise GitHubAPIError("Decoded content is not text")
        sha_before = _extract_sha(decoded)
    except GitHubAPIError as exc:
        msg = str(exc)
        if "404" in msg:
            # The GitHub Contents API returns 404 when the file does not yet exist.
            # In that case we treat this as a creation rather than an update.
            is_new_file = True
            sha_before = None
        else:
            raise

    body_bytes = updated_content.encode("utf-8")
    if message is not None:
        commit_message = message
    elif is_new_file:
        commit_message = f"Create {normalized_path}"
    else:
        commit_message = f"Update {normalized_path}"

    # 2) Commit the new content via the GitHub Contents API.
    commit_result = await _perform_github_commit(
        full_name=full_name,
        path=normalized_path,
        message=commit_message,
        body_bytes=body_bytes,
        branch=effective_branch,
        sha=sha_before,
    )

    # 3) Verify by reading the file again from the same branch.
    verified = await _decode_github_content(full_name, normalized_path, effective_branch)
    sha_after = _extract_sha(verified)

    result: Dict[str, Any] = {
        "status": "committed",
        "full_name": full_name,
        "path": normalized_path,
        "branch": effective_branch,
        "message": commit_message,
        "commit": commit_result,
        "verification": {
            "sha_before": sha_before,
            "sha_after": sha_after,
            "html_url": verified.get("html_url"),
        },
    }

    return result


@mcp_tool(
    write_action=False,
    description=("Return a compact overview of a pull request, including files and CI status."),
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
    open_prs = [_normalize_pr_payload(pr) for pr in open_raw if isinstance(pr, dict)]
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
        closed_prs = [_normalize_pr_payload(pr) for pr in closed_raw if isinstance(pr, dict)]
        closed_prs = [pr for pr in closed_prs if pr is not None]

    return {
        "full_name": full_name,
        "branch": branch,
        "head_filter": head_filter,
        "open": open_prs,
        "closed": closed_prs,
    }
