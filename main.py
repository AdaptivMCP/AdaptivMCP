"""GitHub MCP server exposing connector-friendly tools and workflows.

This module is the entry point for the GitHub Model Context Protocol server
used by ChatGPT connectors. It lists the tools, arguments, and behaviors in a
single place so an assistant can decide how to interact with the server without
being pushed toward a particular working style.
"""

import base64
import json
import os
import time
from urllib.parse import parse_qs, urlparse
from typing import Any, Dict, List, Mapping, Optional, Literal
import httpx  # noqa: F401

import github_mcp.server as server  # noqa: F401
import github_mcp.tools_workspace as tools_workspace  # noqa: F401
from github_mcp import http_clients as _http_clients  # noqa: F401
from github_mcp.config import (
    BASE_LOGGER,  # noqa: F401
    FETCH_FILES_CONCURRENCY,
    GITHUB_API_BASE,
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    MAX_CONCURRENCY,
    FILE_CACHE_MAX_BYTES,  # noqa: F401
    FILE_CACHE_MAX_ENTRIES,  # noqa: F401
    TOOL_STDERR_MAX_CHARS,  # noqa: F401
    TOOL_STDIO_COMBINED_MAX_CHARS,  # noqa: F401
    TOOL_STDOUT_MAX_CHARS,  # noqa: F401
    WORKSPACE_BASE_DIR,  # noqa: F401
    )
from github_mcp.exceptions import (
    GitHubAPIError,  # noqa: F401
    GitHubAuthError,
    GitHubRateLimitError,  # noqa: F401
    WriteApprovalRequiredError,  # noqa: F401
    WriteNotAuthorizedError,  # noqa: F401
)
from github_mcp.github_content import (
    _decode_github_content,
    _load_body_from_content_url,
    _resolve_file_sha,  # noqa: F401
)
from github_mcp.file_cache import (
    cache_payload,
    clear_cache,
)
from github_mcp.http_clients import (
    _external_client_instance,  # noqa: F401
    _get_concurrency_semaphore,  # noqa: F401
    _get_github_token,  # noqa: F401
    _github_client_instance,  # noqa: F401
)
from github_mcp.metrics import (
    _METRICS,  # noqa: F401
    _metrics_snapshot,  # noqa: F401
    _reset_metrics_for_tests,  # noqa: F401
)
from github_mcp.mcp_server.decorators import refresh_registered_tool_metadata
from github_mcp.mcp_server.context import (
    REQUEST_MESSAGE_ID,
    REQUEST_PATH,
    REQUEST_RECEIVED_AT,
    REQUEST_SESSION_ID,
)
from github_mcp.server import (
    _REGISTERED_MCP_TOOLS,  # noqa: F401
    CONTROLLER_DEFAULT_BRANCH,
    CONTROLLER_REPO,
    _structured_tool_error,  # noqa: F401
    _github_request,
    mcp_tool,
    register_extra_tools_if_available,
    COMPACT_METADATA_DEFAULT,
    _find_registered_tool,
    _normalize_input_schema,
)
from github_mcp.tools_workspace import commit_workspace, ensure_workspace_clone, render_shell  # noqa: F401
from github_mcp.utils import (
    _effective_ref_for_repo,
    _normalize_repo_path,
    _with_numbered_lines,
)
from github_mcp.workspace import (
    _clone_repo,  # noqa: F401
    _prepare_temp_virtualenv,  # noqa: F401
    _run_shell,  # noqa: F401
    _workspace_path,  # noqa: F401
)
from github_mcp.http_routes.actions_compat import register_actions_compat_routes
from github_mcp.http_routes.healthz import register_healthz_route
from github_mcp.http_routes.tool_registry import register_tool_registry_routes
from starlette.staticfiles import StaticFiles
from starlette.responses import PlainTextResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware




class _CacheControlMiddleware:
    """ASGI middleware to control Cache-Control headers safely for streaming.

    Avoid BaseHTTPMiddleware here because it can interfere with streaming
    responses (SSE).

    - Never cache dynamic streaming endpoints: /sse and /messages
    - Optionally cache static assets: /static/*
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            return await self.app(scope, receive, send)

        path = scope.get('path', '') or ''
        started = False
        completed = False

        async def send_wrapper(message):
            nonlocal started, completed
            if completed:
                return
            if message.get('type') == 'http.response.start':
                if started:
                    return
                started = True
                headers = list(message.get('headers', []))
                # Normalize: remove any existing Cache-Control header if we're overriding.
                def _has_cache_control(hdrs):
                    return any(k.lower() == b'cache-control' for k, _ in hdrs)

                if path.startswith('/static/'):
                    # Honor any explicit Cache-Control set upstream; otherwise make static assets cacheable.
                    if not _has_cache_control(headers):
                        headers.append((b'cache-control', b'public, max-age=31536000, immutable'))
                else:
                    # Default to no-store for everything else so edge caching (or proxies) never cache dynamic endpoints.
                    headers = [(k, v) for (k, v) in headers if k.lower() != b'cache-control']
                    headers.append((b'cache-control', b'no-store'))
                message['headers'] = headers
            elif message.get('type') == 'http.response.body':
                if not message.get('more_body', False):
                    completed = True
            await send(message)

        return await self.app(scope, receive, send_wrapper)



class _RequestContextMiddleware:
    """ASGI middleware that extracts stable identifiers for dedupe and logging.

    For POST /messages, we capture:
      - `session_id` from the query string
      - MCP JSON-RPC `id` from the request body

    These values are stored in contextvars and consumed by the tool decorator
    to suppress duplicate tool invocations caused by upstream retries.

    We avoid BaseHTTPMiddleware to preserve streaming semantics.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http':
            return await self.app(scope, receive, send)

        path = scope.get('path', '') or ''

        # Reset context for this request.
        REQUEST_PATH.set(path)
        REQUEST_RECEIVED_AT.set(time.time())
        REQUEST_SESSION_ID.set(None)
        REQUEST_MESSAGE_ID.set(None)

        # Parse query string for session_id.
        try:
            raw_qs = (scope.get('query_string') or b'').decode('utf-8', errors='ignore')
            qs = parse_qs(raw_qs)
            session_id = (qs.get('session_id') or [None])[0]
            if session_id:
                REQUEST_SESSION_ID.set(str(session_id))
        except Exception:
            pass

        # Only parse JSON body for POST /messages.
        if path.endswith('/messages') and scope.get('method') == 'POST':
            body_chunks: list[bytes] = []
            total = 0
            more_body = True

            async def _drain_body():
                nonlocal more_body, total
                while more_body:
                    msg = await receive()
                    if msg.get('type') != 'http.request':
                        continue
                    chunk = msg.get('body', b'') or b''
                    if chunk:
                        body_chunks.append(chunk)
                        total += len(chunk)
                    more_body = bool(msg.get('more_body'))

            # Drain once, then replay to downstream app.
            await _drain_body()
            body = b''.join(body_chunks)
            try:
                if body:
                    payload = json.loads(body.decode('utf-8', errors='replace'))
                    msg_id = payload.get('id')
                    if msg_id is not None:
                        REQUEST_MESSAGE_ID.set(str(msg_id))
            except Exception:
                pass

            # Replay the drained body to downstream consumers.
            replayed = False

            async def receive_replay():
                nonlocal replayed
                if replayed:
                    return {'type': 'http.request', 'body': b'', 'more_body': False}
                replayed = True
                return {'type': 'http.request', 'body': body, 'more_body': False}

            return await self.app(scope, receive_replay, send)

        return await self.app(scope, receive, send)



# Re-exported symbols used by helper modules and tests that import `main`.
__all__ = [
    "GitHubAPIError",
    "GitHubAuthError",
    "GitHubRateLimitError",
    "WriteApprovalRequiredError",
    "WriteNotAuthorizedError",
    "GITHUB_API_BASE",
    "HTTPX_TIMEOUT",
    "HTTPX_MAX_CONNECTIONS",
    "HTTPX_MAX_KEEPALIVE",
    "MAX_CONCURRENCY",
    "FETCH_FILES_CONCURRENCY",
    "CONTROLLER_REPO",
    "CONTROLLER_DEFAULT_BRANCH",
    "_github_request",
    "get_recent_server_logs",
]
# Exposed for tests that monkeypatch the external HTTP client used for sandbox: URLs.
_http_client_external: httpx.AsyncClient | None = None

LOGGER = BASE_LOGGER.getChild("main")

# Keep selected symbols in main for tests/backwards-compat and for impl modules.
_EXPORT_COMPAT = (
    COMPACT_METADATA_DEFAULT,
    _find_registered_tool,
    _normalize_input_schema,
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
    """Perform a Contents API commit and then refresh the workspace clone."""
    from github_mcp.main_tools.workspace_sync import _perform_github_commit_and_refresh_workspace as _impl
    return await _impl(full_name=full_name, path=path, message=message, branch=branch, body_bytes=body_bytes, sha=sha)




async def _perform_github_commit(
    full_name: str,
    *,
    branch: str,
    path: str,
    message: str,
    body_bytes: bytes,
    sha: Optional[str],
    committer: Optional[Dict[str, str]] = None,
    author: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Compat wrapper for github_mcp.github_content._perform_github_commit."""
    from github_mcp.github_content import _perform_github_commit as _impl
    return await _impl(
        full_name,
        branch=branch,
        path=path,
        message=message,
        body_bytes=body_bytes,
        sha=sha,
        committer=committer,
        author=author,
    )
def __getattr__(name: str):
    if name == "WRITE_ALLOWED":
        return server.WRITE_ALLOWED
    raise AttributeError(name)


# Recalculate write-allowed state on first import to honor updated environment variables when
# ``main`` is reloaded in tests without clobbering runtime toggles.
if not getattr(server, "_WRITE_ALLOWED_INITIALIZED", False):
    server.WRITE_ALLOWED = server.WRITE_ALLOWED if hasattr(server, "WRITE_ALLOWED") else True
    server._WRITE_ALLOWED_INITIALIZED = True

register_extra_tools_if_available()

# Expose an ASGI app for hosting via uvicorn/Render. The FastMCP server lazily
# constructs a Starlette application through ``http_app`` (newer releases), but
# older versions used ``sse_app``/``app`` helpers. Build the app once at import
# time so ``uvicorn main:app`` works across versions.
#
# Force the SSE transport so the controller serves ``/sse`` again. FastMCP 2.14
# defaults to the streamable HTTP transport, which removed the SSE route and
# caused the public endpoint to return ``404 Not Found``. Using the SSE transport
# keeps the documented ``/sse`` path working for existing clients.
if hasattr(server.mcp, "http_app"):
    try:
        app = server.mcp.http_app(path="/sse", transport="sse")
    except TypeError:
        try:
            app = server.mcp.http_app(transport="sse")
        except TypeError:
            app = server.mcp.http_app()
elif hasattr(server.mcp, "sse_app"):
    try:
        app = server.mcp.sse_app(path="/sse")
    except TypeError:
        app = server.mcp.sse_app()
elif hasattr(server.mcp, "app"):
    app_factory = server.mcp.app
    if callable(app_factory):
        try:
            app = app_factory(path="/sse")
        except TypeError:
            app = app_factory()
    else:
        app = app_factory
else:
    # In minimal/test environments FastMCP may be absent or may not expose an ASGI
    # app factory. Avoid raising at import time so helper functions (e.g.
    # _configure_trusted_hosts) remain testable.
    try:
        app = Starlette()
    except Exception:
        app = None


def _extract_hostname(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if "://" in cleaned:
        parsed = urlparse(cleaned)
        host = parsed.hostname or parsed.netloc
        return host or None
    return cleaned


def _render_external_hosts() -> list[str]:
    hostnames: list[str] = []
    for env_name in ("RENDER_EXTERNAL_HOSTNAME", "RENDER_EXTERNAL_URL"):
        hostname = _extract_hostname(os.getenv(env_name))
        if hostname:
            hostnames.append(hostname)
    return hostnames


def _configure_trusted_hosts(app_instance) -> None:
    allowed_hosts_env = os.getenv("ALLOWED_HOSTS")
    if allowed_hosts_env:
        allowed_hosts = [host.strip() for host in allowed_hosts_env.split(",") if host.strip()]
    else:
        allowed_hosts = ["*"]

    if "*" not in allowed_hosts:
        for render_host in _render_external_hosts():
            if render_host not in allowed_hosts:
                allowed_hosts.append(render_host)

    app_instance.user_middleware = [
        middleware for middleware in app_instance.user_middleware if middleware.cls is not TrustedHostMiddleware
    ]
    app_instance.middleware_stack = None
    app_instance.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)


if app is not None:
    _configure_trusted_hosts(app)
app.add_middleware(_CacheControlMiddleware)
app.add_middleware(_RequestContextMiddleware)


async def _handle_value_error(request, exc):
    if str(exc) == "Request validation failed":
        return PlainTextResponse("Request validation failed", status_code=400)
    raise exc


app.add_exception_handler(ValueError, _handle_value_error)



try:
    app.mount("/static", StaticFiles(directory="assets"), name="static")
except Exception:
    # Static assets are optional; failures should not prevent server startup.
    pass

register_actions_compat_routes(app, server)
register_healthz_route(app)
register_tool_registry_routes(app)


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
    )


async def run_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
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
    )


async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
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


@mcp_tool(write_action=True)
def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    """Update the WRITE_ALLOWED state used for write gating."""

    import github_mcp.mcp_server.context as _ctx

    _ctx.set_write_allowed(bool(approved))
    refresh_registered_tool_metadata(server.WRITE_ALLOWED)
    return {"write_allowed": bool(server.WRITE_ALLOWED)}


# ------------------------------------------------------------------------------
# Read-only tools


@mcp_tool(
    write_action=False,
    description="List recent tool invocation events captured in memory.",
    tags=["observability", "tools", "events"],
)
def get_recent_tool_events(limit: int = 50, include_success: bool = True) -> Dict[str, Any]:
    """Delegates to github_mcp.main_tools.observability.get_recent_tool_events."""
    from github_mcp.main_tools.observability import get_recent_tool_events as _impl
    return _impl(limit=limit, include_success=include_success)


@mcp_tool(
    write_action=False,
    description="List recent server-side errors captured in memory.",
    tags=["observability", "logs", "errors"],
)
def get_recent_server_errors(limit: int = 50) -> Dict[str, Any]:
    """Delegates to github_mcp.main_tools.observability.get_recent_server_errors."""
    from github_mcp.main_tools.observability import get_recent_server_errors as _impl
    return _impl(limit=limit)


@mcp_tool(
    write_action=False,
    description="Return recent server-side logs captured in memory (useful when provider logs are unavailable).",
    tags=["observability", "logs"],
)
def get_recent_server_logs(limit: int = 100, min_level: str = "INFO") -> Dict[str, Any]:
    """Return recent server-side logs captured in memory.

    Use this when debugging tool behavior in environments where you cannot
    access provider logs.
    """

    from github_mcp.main_tools.server_logs import get_recent_server_logs as _impl

    return _impl(limit=limit, min_level=min_level)


@mcp_tool(
    write_action=False,
    description="Fetch recent logs from Render (requires RENDER_API_KEY). Render /logs requires ownerId; pass ownerId or set RENDER_OWNER_ID; otherwise the tool will attempt to resolve it from the service id.",
    tags=["render", "observability", "logs"],
)
async def list_render_logs(
    ownerId: Optional[str] = None,
    resource: Optional[List[str]] = None,
    level: Optional[List[str]] = None,
    type: Optional[List[str]] = None,
    text: Optional[List[str]] = None,
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    direction: Optional[str] = None,
    limit: Optional[int] = 100,
) -> Any:
    from github_mcp.main_tools.render_observability import list_render_logs as _impl

    return await _impl(
        ownerId=ownerId,
        resource=resource,
        level=level,
        type=type,
        text=text,
        startTime=startTime,
        endTime=endTime,
        direction=direction,
        limit=limit,
    )


@mcp_tool(
    write_action=False,
    description="Fetch basic Render service metrics (defaults to RENDER_SERVICE_ID when resourceId is omitted; requires RENDER_API_KEY).",
    tags=["render", "observability", "metrics"],
)
async def get_render_metrics(
    metricTypes: List[str],
    resourceId: Optional[str] = None,
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    resolution: Optional[int] = None,
) -> Dict[str, Any]:
    from github_mcp.main_tools.render_observability import get_render_metrics as _impl

    return await _impl(
        metricTypes=metricTypes,
        resourceId=resourceId,
        startTime=startTime,
        endTime=endTime,
        resolution=resolution,
    )
# ------------------------------------------------------------------------------

@mcp_tool(write_action=False)
async def get_server_config() -> Dict[str, Any]:
    from github_mcp.main_tools.server_config import get_server_config as _impl
    return await _impl()



@mcp_tool(
    write_action=False,
    description="Validate a JSON string and return a normalized form.",
    tags=["meta", "json", "validation"],
)
def validate_json_string(raw: str) -> Dict[str, Any]:
    from github_mcp.main_tools.server_config import validate_json_string as _impl
    return _impl(raw=raw)



@mcp_tool(write_action=False)
async def get_repo_defaults(
    full_name: Optional[str] = None,
) -> Dict[str, Any]:
    from github_mcp.main_tools.server_config import get_repo_defaults as _impl
    return await _impl(full_name=full_name)



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
    from github_mcp.main_tools.diagnostics import pr_smoke_test as _impl
    return await _impl(full_name=full_name, base_branch=base_branch, draft=draft)

@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    from github_mcp.main_tools.repositories import get_rate_limit as _impl
    return await _impl()



@mcp_tool(write_action=False)
async def get_user_login() -> Dict[str, Any]:
    from github_mcp.main_tools.repositories import get_user_login as _impl
    return await _impl()



@mcp_tool(write_action=False)
async def list_repositories(
    affiliation: Optional[str] = None,
    visibility: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    from github_mcp.main_tools.repositories import list_repositories as _impl
    return await _impl(affiliation=affiliation, visibility=visibility, per_page=per_page, page=page)



@mcp_tool(write_action=False)
async def list_repositories_by_installation(
    installation_id: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    from github_mcp.main_tools.repositories import list_repositories_by_installation as _impl
    return await _impl(installation_id=installation_id, per_page=per_page, page=page)



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
    from github_mcp.main_tools.repositories import create_repository as _impl
    return await _impl(name=name, owner=owner, owner_type=owner_type, description=description, homepage=homepage, visibility=visibility, private=private, auto_init=auto_init, gitignore_template=gitignore_template, license_template=license_template, is_template=is_template, has_issues=has_issues, has_projects=has_projects, has_wiki=has_wiki, has_discussions=has_discussions, team_id=team_id, security_and_analysis=security_and_analysis, template_full_name=template_full_name, include_all_branches=include_all_branches, topics=topics, create_payload_overrides=create_payload_overrides, update_payload_overrides=update_payload_overrides, clone_to_workspace=clone_to_workspace, clone_ref=clone_ref)



@mcp_tool(write_action=False)
async def list_recent_issues(
    filter: str = "assigned",
    state: str = "open",
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    from github_mcp.main_tools.issues import list_recent_issues as _impl
    return await _impl(filter=filter, state=state, per_page=per_page, page=page)




@mcp_tool(write_action=False)
async def list_repository_issues(
    full_name: str,
    state: str = "open",
    labels: Optional[List[str]] = None,
    assignee: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    from github_mcp.main_tools.issues import list_repository_issues as _impl
    return await _impl(full_name=full_name, state=state, labels=labels, assignee=assignee, per_page=per_page, page=page)




@mcp_tool(write_action=False)
async def fetch_issue(full_name: str, issue_number: int) -> Dict[str, Any]:
    from github_mcp.main_tools.issues import fetch_issue as _impl
    return await _impl(full_name=full_name, issue_number=issue_number)




@mcp_tool(write_action=False)
async def fetch_issue_comments(
    full_name: str, issue_number: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    from github_mcp.main_tools.issues import fetch_issue_comments as _impl
    return await _impl(full_name=full_name, issue_number=issue_number, per_page=per_page, page=page)




@mcp_tool(write_action=False)
async def fetch_pr(full_name: str, pull_number: int) -> Dict[str, Any]:
    from github_mcp.main_tools.pull_requests import fetch_pr as _impl
    return await _impl(full_name=full_name, pull_number=pull_number)



@mcp_tool(write_action=False)
async def get_pr_info(full_name: str, pull_number: int) -> Dict[str, Any]:
    from github_mcp.main_tools.pull_requests import get_pr_info as _impl
    return await _impl(full_name=full_name, pull_number=pull_number)



@mcp_tool(write_action=False)
async def fetch_pr_comments(
    full_name: str, pull_number: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    from github_mcp.main_tools.pull_requests import fetch_pr_comments as _impl
    return await _impl(full_name=full_name, pull_number=pull_number, per_page=per_page, page=page)



@mcp_tool(write_action=False)
async def list_pr_changed_filenames(
    full_name: str, pull_number: int, per_page: int = 100, page: int = 1
) -> Dict[str, Any]:
    from github_mcp.main_tools.pull_requests import list_pr_changed_filenames as _impl
    return await _impl(full_name=full_name, pull_number=pull_number, per_page=per_page, page=page)



@mcp_tool(write_action=False)
async def get_commit_combined_status(full_name: str, ref: str) -> Dict[str, Any]:
    from github_mcp.main_tools.pull_requests import get_commit_combined_status as _impl
    return await _impl(full_name=full_name, ref=ref)



@mcp_tool(write_action=False)
async def get_issue_comment_reactions(
    full_name: str, comment_id: int, per_page: int = 30, page: int = 1
) -> Dict[str, Any]:
    from github_mcp.main_tools.issues import get_issue_comment_reactions as _impl
    return await _impl(full_name=full_name, comment_id=comment_id, per_page=per_page, page=page)




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
    from github_mcp.main_tools.files import move_file as _impl
    return await _impl(full_name=full_name, from_path=from_path, to_path=to_path, branch=branch, message=message)



@mcp_tool(write_action=False)
async def get_file_contents(
    full_name: str,
    path: str,
    ref: str = "main",
    *,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch a single file from GitHub and decode base64 to UTF-8 text."""
    # Back-compat: some callers send 'branch' instead of 'ref'.
    if branch:
        ref = branch

    decoded = await _decode_github_content(full_name, path, ref)
    _cache_file_result(full_name=full_name, path=path, ref=ref, decoded=decoded)
    return decoded


@mcp_tool(write_action=False)
async def fetch_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
) -> Dict[str, Any]:
    from github_mcp.main_tools.content_cache import fetch_files as _impl
    return await _impl(full_name=full_name, paths=paths, ref=ref)



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
    from github_mcp.main_tools.content_cache import get_cached_files as _impl
    return await _impl(full_name=full_name, paths=paths, ref=ref)



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
    from github_mcp.main_tools.content_cache import cache_files as _impl
    return await _impl(full_name=full_name, paths=paths, ref=ref, refresh=refresh)



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
    from github_mcp.main_tools.content_cache import list_repository_tree as _impl
    return await _impl(full_name=full_name, ref=ref, path_prefix=path_prefix, recursive=recursive, max_entries=max_entries, include_blobs=include_blobs, include_trees=include_trees)



@mcp_tool(write_action=False)
async def graphql_query(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from github_mcp.main_tools.querying import graphql_query as _impl
    return await _impl(query=query, variables=variables)



@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    from github_mcp.main_tools.querying import fetch_url as _impl
    return await _impl(url=url)



@mcp_tool(write_action=False)
async def search(
    query: str,
    search_type: Literal["code", "repositories", "issues", "commits", "users"] = "code",
    per_page: int = 30,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[Literal["asc", "desc"]] = None,
) -> Dict[str, Any]:
    from github_mcp.main_tools.querying import search as _impl
    return await _impl(query=query, search_type=search_type, per_page=per_page, page=page, sort=sort, order=order)



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
    """Decode a zipped GitHub Actions job logs payload into a readable string."""
    from github_mcp.utils import _decode_zipped_job_logs as _impl
    return _impl(content)



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
        "List available MCP tools with a compact description. "
        "Use describe_tool (or list_all_actions with include_parameters=true) when you need full schemas."
    ),
)
async def list_tools(
    only_write: bool = False,
    only_read: bool = False,
    name_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Lightweight tool catalog."""
    from github_mcp.main_tools.introspection import list_tools as _impl
    return await _impl(only_write=only_write, only_read=only_read, name_prefix=name_prefix)



@mcp_tool(write_action=False)
def list_all_actions(
    include_parameters: bool = False, compact: Optional[bool] = None
) -> Dict[str, Any]:
    """Enumerate every available MCP tool with optional schemas.

    This helper exposes a structured catalog of all tools so assistants can see
    the full command surface without reading this file. It is intentionally
    read-only and can therefore be called before writes are enabled.

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
        "Return optional schema for one or more tools. "
        "Prefer this over manually scanning list_all_actions in long sessions."
    ),
)
async def describe_tool(
    name: Optional[str] = None,
    names: Optional[List[str]] = None,
    include_parameters: bool = True,
    tool_name: Optional[str] = None,
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

    # Back-compat: some callers send tool_name instead of name.
    if tool_name:
        if names is not None:
            raise ValueError("Provide either tool_name/name or names (not both).")
        if name is None:
            name = tool_name
        elif name != tool_name:
            raise ValueError("Provide only one of tool_name or name (or set them equal).")

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
    from github_mcp.main_tools.issues import get_issue_overview as _impl
    return await _impl(full_name=full_name, issue_number=issue_number)



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
    from github_mcp.main_tools.pull_requests import list_pull_requests as _impl
    return await _impl(full_name=full_name, state=state, head=head, base=base, per_page=per_page, page=page)



@mcp_tool(write_action=True)
async def merge_pull_request(
    full_name: str,
    number: int,
    merge_method: Literal["merge", "squash", "rebase"] = "squash",
    commit_title: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    from github_mcp.main_tools.pull_requests import merge_pull_request as _impl
    return await _impl(full_name=full_name, number=number, merge_method=merge_method, commit_title=commit_title, commit_message=commit_message)



@mcp_tool(write_action=True)
async def close_pull_request(full_name: str, number: int) -> Dict[str, Any]:
    from github_mcp.main_tools.pull_requests import close_pull_request as _impl
    return await _impl(full_name=full_name, number=number)



@mcp_tool(write_action=True)
async def comment_on_pull_request(
    full_name: str,
    number: int,
    body: str,
) -> Dict[str, Any]:
    from github_mcp.main_tools.pull_requests import comment_on_pull_request as _impl
    return await _impl(full_name=full_name, number=number, body=body)



@mcp_tool(write_action=True)
async def create_issue(
    full_name: str,
    title: str,
    body: Optional[str] = None,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a GitHub issue in the given repository."""
    from github_mcp.main_tools.issues import create_issue as _impl
    return await _impl(full_name=full_name, title=title, body=body, labels=labels, assignees=assignees)


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
    """Update fields on an existing GitHub issue."""
    from github_mcp.main_tools.issues import update_issue as _impl
    return await _impl(full_name=full_name, issue_number=issue_number, title=title, body=body, state=state, labels=labels, assignees=assignees)


@mcp_tool(write_action=True)
async def comment_on_issue(
    full_name: str,
    issue_number: int,
    body: str,
) -> Dict[str, Any]:
    """Post a comment on an issue."""
    from github_mcp.main_tools.issues import comment_on_issue as _impl
    return await _impl(full_name=full_name, issue_number=issue_number, body=body)


@mcp_tool(write_action=False)
async def open_issue_context(full_name: str, issue_number: int) -> Dict[str, Any]:
    """Return an issue plus related branches and pull requests."""
    from github_mcp.main_tools.issues import open_issue_context as _impl
    return await _impl(full_name=full_name, issue_number=issue_number)



def _normalize_issue_payload(raw_issue: Any) -> Optional[Dict[str, Any]]:
    from github_mcp.main_tools.normalize import normalize_issue_payload as _impl
    return _impl(raw_issue=raw_issue)



def _normalize_pr_payload(raw_pr: Any) -> Optional[Dict[str, Any]]:
    from github_mcp.main_tools.normalize import normalize_pr_payload as _impl
    return _impl(raw_pr=raw_pr)



def _normalize_branch_summary(summary: Any) -> Optional[Dict[str, Any]]:
    from github_mcp.main_tools.normalize import normalize_branch_summary as _impl
    return _impl(summary=summary)



@mcp_tool(write_action=False)
async def resolve_handle(full_name: str, handle: str) -> Dict[str, Any]:
    from github_mcp.main_tools.handles import resolve_handle as _impl
    return await _impl(full_name=full_name, handle=handle)



# ------------------------------------------------------------------------------
# Branch / commit / PR helpers
# ------------------------------------------------------------------------------



@mcp_tool(write_action=True)
async def create_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    from github_mcp.main_tools.branches import create_branch as _impl
    return await _impl(full_name=full_name, branch=branch, from_ref=from_ref)


@mcp_tool(write_action=True)
async def ensure_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    from github_mcp.main_tools.branches import ensure_branch as _impl
    return await _impl(full_name=full_name, branch=branch, from_ref=from_ref)



@mcp_tool(write_action=False)
async def get_branch_summary(full_name: str, branch: str, base: str = "main") -> Dict[str, Any]:
    from github_mcp.main_tools.branches import get_branch_summary as _impl
    return await _impl(full_name=full_name, branch=branch, base=base)



@mcp_tool(write_action=False)
async def get_latest_branch_status(
    full_name: str, branch: str, base: str = "main"
) -> Dict[str, Any]:
    from github_mcp.main_tools.branches import get_latest_branch_status as _impl
    return await _impl(full_name=full_name, branch=branch, base=base)



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

    If this tool call fails in the hosted environment, use the workspace flow: `run_command` to create or reuse the PR.
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
    from github_mcp.main_tools.files import create_file as _impl
    return await _impl(full_name=full_name, path=path, content=content, branch=branch, message=message)



@mcp_tool(write_action=True)
async def apply_text_update_and_commit(
    full_name: str,
    path: str,
    updated_content: str,
    *,
    branch: str = "main",
    message: Optional[str] = None,
    return_diff: bool = False,
) -> Dict[str, Any]:
    from github_mcp.main_tools.files import apply_text_update_and_commit as _impl
    return await _impl(full_name=full_name, path=path, updated_content=updated_content, branch=branch, message=message, return_diff=return_diff)



@mcp_tool(
    write_action=False,
    description=("Return a compact overview of a pull request, including files and CI status."),
)
async def get_pr_overview(full_name: str, pull_number: int) -> Dict[str, Any]:
    # Summarize a pull request so I can decide what to do next.
    #
    # This helper is read-only and safe to call before any write actions.

    from github_mcp.main_tools.pull_requests import get_pr_overview as _impl
    return await _impl(full_name=full_name, pull_number=pull_number)



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
    from github_mcp.main_tools.pull_requests import recent_prs_for_branch as _impl
    return await _impl(full_name=full_name, branch=branch, include_closed=include_closed, per_page_open=per_page_open, per_page_closed=per_page_closed)
