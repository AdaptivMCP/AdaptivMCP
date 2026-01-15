from __future__ import annotations

import os
import subprocess
import shutil
import sys
import platform
import uuid
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
from github_mcp.render_api import render_request
from github_mcp.exceptions import GitHubAPIError


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

    # Runtime/platform context (always informational)
    add_check(
        "runtime",
        "ok",
        "Runtime metadata",
        {
            "python": sys.version.split("\n")[0],
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "executable": sys.executable,
            "pid": os.getpid(),
        },
    )

    # Render/host environment signals (best-effort; do not assume Render)
    env_signals: Dict[str, Any] = {}
    for key in (
        "RENDER",
        "RENDER_SERVICE_ID",
        "RENDER_INSTANCE_ID",
        "RENDER_EXTERNAL_HOSTNAME",
        "RENDER_REGION",
        "RENDER_GIT_COMMIT",
        "RENDER_GIT_BRANCH",
    ):
        if key in os.environ:
            env_signals[key.lower()] = os.environ.get(key)
    add_check(
        "deployment_signals",
        "ok",
        "Deployment environment signals (best-effort)",
        env_signals,
    )

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

    # ------------------------------------------------------------------
    # Tool registry sanity checks
    # ------------------------------------------------------------------
    # This server relies on side-effect registration (decorators execute at import
    # time). For operator confidence (and to catch bad deploys), confirm that the
    # expected GitHub + Render tool surfaces are present.
    try:
        from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS
        from github_mcp.main_tools.introspection import list_all_actions

        catalog = list_all_actions(include_parameters=False, compact=True)
        tools = catalog.get("tools") if isinstance(catalog, dict) else None
        tool_names = {
            t.get("name") for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)
        }
        # Minimum expected surface (Render + core introspection).
        expected = {
            # Introspection
            "list_all_actions",
            "list_tools",
            "describe_tool",
            # Render (canonical)
            "list_render_owners",
            "list_render_services",
            "get_render_service",
            "list_render_deploys",
            "get_render_deploy",
            "create_render_deploy",
            "cancel_render_deploy",
            "rollback_render_deploy",
            "restart_render_service",
            "get_render_logs",
            "list_render_logs",
            # Render (aliases)
            "render_list_owners",
            "render_list_services",
            "render_get_service",
            "render_list_deploys",
            "render_get_deploy",
            "render_create_deploy",
            "render_cancel_deploy",
            "render_rollback_deploy",
            "render_restart_service",
            "render_get_logs",
            "render_list_logs",
        }

        missing = sorted(name for name in expected if name not in tool_names)
        registered_count = (
            len(_REGISTERED_MCP_TOOLS) if isinstance(_REGISTERED_MCP_TOOLS, list) else None
        )
        unique_count = len(tool_names)

        if missing:
            add_check(
                "tool_registry",
                "error",
                "Tool registry is missing expected tools; deploy may have failed to import/register all tools",
                {
                    "registered_entries": registered_count,
                    "unique_tools": unique_count,
                    "missing": missing,
                },
            )
        else:
            add_check(
                "tool_registry",
                "ok",
                "Tool registry contains expected GitHub + Render tool surfaces",
                {
                    "registered_entries": registered_count,
                    "unique_tools": unique_count,
                },
            )
    except Exception as exc:
        add_check(
            "tool_registry",
            "warning",
            "Could not validate tool registry (best-effort)",
            {"error_type": type(exc).__name__, "error": str(exc)},
        )

    # Remote validation for controller repo/branch, only if token is usable.
    if token_ok:
        # ------------------------------------------------------------------
        # Token introspection (best-effort)
        # ------------------------------------------------------------------
        # GitHub exposes OAuth/PAT scopes in response headers for classic tokens.
        # Fine-grained PATs typically do not include X-OAuth-Scopes.
        def _get_header_ci(headers: Any, key: str) -> Optional[str]:
            if not isinstance(headers, dict):
                return None
            for k, v in headers.items():
                if isinstance(k, str) and k.lower() == key.lower():
                    return str(v)
            return None

        token_details: Dict[str, Any] = {
            "env_var": token_env_var,
            "length": len(raw_token or "") if raw_token is not None else None,
            "authorization_scheme": "Bearer",
        }

        scope_list: List[str] = []
        token_type_inferred: str = "unknown"

        try:
            user_resp = await m._github_request("GET", "/user")
        except Exception as exc:
            add_check(
                "github_token_details",
                "warning",
                "Unable to fetch /user; token may be invalid or missing required permissions",
                {"error_type": type(exc).__name__, "error": str(exc), **token_details},
            )
        else:
            headers = user_resp.get("headers")
            scopes = _get_header_ci(headers, "X-OAuth-Scopes")
            accepted = _get_header_ci(headers, "X-Accepted-OAuth-Scopes")

            user_json = user_resp.get("json")
            if isinstance(user_json, dict):
                token_details.update(
                    {
                        "login": user_json.get("login"),
                        "id": user_json.get("id"),
                        "account_type": user_json.get("type"),
                    }
                )

            if isinstance(scopes, str) and scopes.strip():
                scope_list = [s.strip() for s in scopes.split(",") if s.strip()]
            token_details["oauth_scopes"] = scope_list
            if isinstance(accepted, str) and accepted.strip():
                token_details["accepted_oauth_scopes"] = [
                    s.strip() for s in accepted.split(",") if s.strip()
                ]

            # Infer token type.
            token_type = "unknown"
            if scope_list:
                token_type = "classic_pat_or_oauth"
            else:
                # Detect GitHub App tokens via /app (works only for app auth).
                try:
                    await m._github_request("GET", "/app")
                except Exception:
                    token_type = "fine_grained_pat_or_unknown"
                else:
                    token_type = "github_app_token"
            token_details["token_type_inferred"] = token_type
            token_type_inferred = token_type

            # Provide a lightweight "what can this token do" hint for classic PAT scopes.
            if scope_list:
                common_required = {
                    # Common read/write repo operations
                    "repo": "Read/write private repositories",
                    "public_repo": "Read/write public repositories",
                    "workflow": "Trigger GitHub Actions workflows",
                    "read:org": "Read org membership (useful for org repo discovery)",
                    "write:packages": "Publish packages",
                    "delete_repo": "Delete repositories",
                }
                token_details["scope_hints"] = {
                    scope: common_required.get(scope)
                    for scope in scope_list
                    if scope in common_required
                }

            add_check(
                "github_token_details",
                "ok",
                "GitHub token details (best-effort; scopes only available for classic tokens)",
                token_details,
            )

        # Rate limit snapshot (useful for diagnosing 403/429)
        try:
            rl_resp = await m._github_request("GET", "/rate_limit")
        except Exception as exc:
            add_check(
                "github_rate_limit",
                "warning",
                "Unable to fetch GitHub rate limit; requests may still work but diagnostics are incomplete",
                {"error_type": type(exc).__name__, "error": str(exc)},
            )
        else:
            rl_json = rl_resp.get("json")
            core = None
            graphql = None
            search = None
            if isinstance(rl_json, dict):
                resources = rl_json.get("resources")
                if isinstance(resources, dict):
                    core = resources.get("core")
                    graphql = resources.get("graphql")
                    search = resources.get("search")
            add_check(
                "github_rate_limit",
                "ok",
                "GitHub rate limit snapshot",
                {"core": core, "graphql": graphql, "search": search},
            )

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

            # ------------------------------------------------------------------
            # Capability probes (best-effort)
            # ------------------------------------------------------------------
            # These probes are designed to be safe: they avoid creating/modifying
            # resources. Where a capability cannot be confirmed without side
            # effects (e.g. workflow dispatch), we provide an inferred result.
            probes: List[Dict[str, Any]] = []

            async def _probe_get(name: str, path: str, *, params: Optional[Dict[str, Any]] = None):
                try:
                    await m._github_request("GET", path, params=params)
                except Exception as exc:
                    probes.append(
                        {
                            "probe": name,
                            "mode": "actual",
                            "result": "fail",
                            "details": {"error_type": type(exc).__name__, "error": str(exc)},
                        }
                    )
                else:
                    probes.append({"probe": name, "mode": "actual", "result": "pass"})

            # 1) Can list workflows?
            await _probe_get(
                "can_list_workflows",
                f"/repos/{controller_repo}/actions/workflows",
                params={"per_page": 1},
            )

            # 2) Can create PR? Use an invalid head ref to avoid side effects.
            # If the endpoint is reachable and token has access, GitHub returns
            # 422 Validation Failed. Auth/permission failures return 401/403/404.
            bogus_head = f"mcp-capability-probe-{uuid.uuid4()}"
            try:
                await m._github_request(
                    "POST",
                    f"/repos/{controller_repo}/pulls",
                    json_body={
                        "title": "mcp capability probe",
                        "head": bogus_head,
                        "base": controller_branch,
                        "body": "Capability probe (expected to fail validation)",
                        "draft": True,
                    },
                )
            except GitHubAPIError as exc:
                status_code = getattr(exc, "status_code", None)
                if status_code == 422:
                    probes.append({"probe": "can_create_pr", "mode": "actual", "result": "pass"})
                else:
                    probes.append(
                        {
                            "probe": "can_create_pr",
                            "mode": "actual",
                            "result": "fail",
                            "details": {"status_code": status_code, "error": str(exc)},
                        }
                    )
            except Exception as exc:
                probes.append(
                    {
                        "probe": "can_create_pr",
                        "mode": "actual",
                        "result": "fail",
                        "details": {"error_type": type(exc).__name__, "error": str(exc)},
                    }
                )
            else:
                # Unexpected success; treat as pass but surface as noteworthy.
                probes.append(
                    {
                        "probe": "can_create_pr",
                        "mode": "actual",
                        "result": "pass",
                        "details": {"note": "Unexpected success creating PR probe payload"},
                    }
                )

            # 3) Can dispatch workflow? Avoid side effects by inference.
            # - Classic PATs/OAuth tokens: require the "workflow" scope.
            # - Fine-grained PATs: scopes are not reported; cannot confirm without
            #   an actual dispatch (side effect).
            list_workflows_ok = any(
                p.get("probe") == "can_list_workflows" and p.get("result") == "pass" for p in probes
            )
            workflow_scope = "workflow" in (scope_list or [])
            inferred_dispatch = workflow_scope and list_workflows_ok
            dispatch_result = "pass" if inferred_dispatch else "fail"
            dispatch_details: Dict[str, Any] = {
                "token_type_inferred": token_type_inferred,
                "workflow_scope_present": workflow_scope,
                "list_workflows_ok": list_workflows_ok,
                "note": "Inferred without dispatching a workflow run (no side effects).",
            }
            if token_type_inferred == "fine_grained_pat_or_unknown" and not workflow_scope:
                dispatch_details["caveat"] = (
                    "Fine-grained PAT permissions are not surfaced via OAuth scope headers; dispatch may still work."
                )
            probes.append(
                {
                    "probe": "can_dispatch_workflow",
                    "mode": "inferred",
                    "result": dispatch_result,
                    "details": dispatch_details,
                }
            )

            probe_level = "ok" if all(p.get("result") == "pass" for p in probes) else "warning"
            add_check(
                "capability_probes",
                probe_level,
                "Capability probes (safe, best-effort)",
                {"repo": controller_repo, "branch": controller_branch, "probes": probes},
            )

            # Surface the repo permissions block prominently for clarity.
            add_check(
                "controller_repo_permissions",
                "ok" if isinstance(permissions, dict) and permissions else "warning",
                "Repository permissions as reported by GitHub (permission-aware tokens only)",
                {"full_name": controller_repo, "permissions": permissions},
            )

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

        # Render API validation + owner snapshot (best-effort, read-only).
        try:
            owners_resp = await render_request("GET", "/owners", params={"limit": 5})
        except Exception as exc:
            add_check(
                "render_api",
                "warning",
                "Unable to call Render API with the configured token",
                {"error_type": type(exc).__name__, "error": str(exc)},
            )
        else:
            owners_json = owners_resp.get("json") if isinstance(owners_resp, dict) else None
            owners: List[Dict[str, Any]] = []
            cursor = None
            if isinstance(owners_json, dict):
                # Some Render API responses are paginated objects.
                items = (
                    owners_json.get("owners") or owners_json.get("items") or owners_json.get("data")
                )
                if isinstance(items, list):
                    owners = [o for o in items if isinstance(o, dict)]
                cursor = owners_json.get("cursor") or owners_json.get("nextCursor")
            elif isinstance(owners_json, list):
                owners = [o for o in owners_json if isinstance(o, dict)]

            owner_samples: List[Dict[str, Any]] = []
            for o in owners[:5]:
                owner_samples.append(
                    {
                        "id": o.get("id"),
                        "name": o.get("name") or o.get("displayName"),
                        "type": o.get("type"),
                        "owner_type": o.get("ownerType") or o.get("owner_type"),
                    }
                )

            add_check(
                "render_api",
                "ok",
                "Render API is reachable with the configured token (owner sample)",
                {
                    "owners_sample": owner_samples,
                    "next_cursor": cursor,
                },
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
