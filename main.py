"""GitHub MCP server exposing connector-friendly tools and workflows.

This module is the entry point for the GitHub Model Context Protocol server
used by ChatGPT connectors. It lists the tools, arguments, and behaviors in a
single place so an assistant can decide how to interact with the server without
being pushed toward a particular working style. See ``ASSISTANT_WORKFLOWS.md``
for optional, non-binding examples of how the tools can fit together.
"""

import os
import re
import asyncio
import base64
import tempfile
import shutil
import uuid
import io
import zipfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from anyio import ClosedResourceError
from mcp.types import ToolAnnotations
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import PlainTextResponse


# ------------------------------------------------------------------------------
# Configuration and globals
# ------------------------------------------------------------------------------

GITHUB_PAT = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")

HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", 150))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", 300))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", 200))

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", 80))
FETCH_FILES_CONCURRENCY = int(
    os.environ.get("FETCH_FILES_CONCURRENCY", MAX_CONCURRENCY)
)

TOOL_STDOUT_MAX_CHARS = 12000
TOOL_STDERR_MAX_CHARS = int(os.environ.get("TOOL_STDERR_MAX_CHARS", "12000"))
LOGS_MAX_CHARS = 16000

GIT_AUTHOR_NAME = os.environ.get("GIT_AUTHOR_NAME", "Ally")
GIT_AUTHOR_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "ally@example.com")
GIT_COMMITTER_NAME = os.environ.get("GIT_COMMITTER_NAME", GIT_AUTHOR_NAME)
GIT_COMMITTER_EMAIL = os.environ.get("GIT_COMMITTER_EMAIL", GIT_AUTHOR_EMAIL)


def _env_flag(name: str, default: bool = False) -> bool:
    """Parse a boolean-like environment variable.

    Accepts common truthy strings (``1``, ``true``, ``yes``, ``on``) in a
    case-insensitive way and falls back to ``default`` when the variable is
    unset. This keeps write gating predictable even when deployers set
    ``GITHUB_MCP_AUTO_APPROVE`` to values other than ``1``.
    """

    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


WRITE_ALLOWED = _env_flag("GITHUB_MCP_AUTO_APPROVE", False)


def _with_numbered_lines(text: str) -> List[Dict[str, Any]]:
    """Return a list of dicts pairing 1-based line numbers with text."""

    return [{"line": idx, "text": line} for idx, line in enumerate(text.splitlines(), 1)]


def _decode_zipped_job_logs(zip_bytes: bytes) -> str:
    """Extract and concatenate text files from a zipped job log archive."""

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
            parts: List[str] = []
            for name in sorted(
                entry
                for entry in zip_file.namelist()
                if not entry.endswith("/")
            ):
                with zip_file.open(name) as handle:
                    content = handle.read().decode("utf-8", errors="replace")
                parts.append(f"[{name}]\n{content}".rstrip())
            return "\n\n".join(parts)
    except Exception:
        return ""

_http_client_github: Optional[httpx.AsyncClient] = None
_http_client_external: Optional[httpx.AsyncClient] = None
_concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
_background_read_jobs: Dict[str, Dict[str, Any]] = {}
_background_read_lock = asyncio.Lock()
_background_read_tasks: Dict[str, asyncio.Task[Any]] = {}

# json_response is configured per transport; do not pass it here.
mcp = FastMCP("GitHub Fast MCP")

# Suppress noisy tracebacks when SSE clients disconnect mid-response. The
# underlying MemoryObjectSendStream raises ClosedResourceError when we attempt
# to send on a closed stream; swallow it so disconnects are treated as routine.
from mcp.shared import session as mcp_shared_session

_orig_send_response = mcp_shared_session.BaseSession._send_response


async def _quiet_send_response(self, request_id, response):
    try:
        return await _orig_send_response(self, request_id, response)
    except ClosedResourceError:
        return None


mcp_shared_session.BaseSession._send_response = _quiet_send_response


# ------------------------------------------------------------------------------
# Exceptions
# ------------------------------------------------------------------------------


class GitHubAuthError(Exception):
    pass


class GitHubAPIError(Exception):
    pass


class WriteNotAuthorizedError(Exception):
    pass


# ------------------------------------------------------------------------------
# HTTP client helpers
# ------------------------------------------------------------------------------


def _get_github_token() -> str:
    token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN must be set")
    return token


def _github_client_instance() -> httpx.AsyncClient:
    global _http_client_github
    if _http_client_github is None:
        token = _get_github_token()
        _http_client_github = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "chatgpt-mcp-github",
            },
            timeout=HTTPX_TIMEOUT,
            limits=httpx.Limits(
                max_connections=HTTPX_MAX_CONNECTIONS,
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
            ),
            http2=bool(int(os.environ.get("HTTPX_HTTP2", "1"))),
        )
    return _http_client_github


def _external_client_instance() -> httpx.AsyncClient:
    global _http_client_external
    if _http_client_external is None:
        _http_client_external = httpx.AsyncClient(
            timeout=HTTPX_TIMEOUT,
            limits=httpx.Limits(
                max_connections=HTTPX_MAX_CONNECTIONS,
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
            ),
            http2=bool(int(os.environ.get("HTTPX_HTTP2", "1"))),
        )
    return _http_client_external


async def _github_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    expect_json: bool = True,
    text_max_chars: int = LOGS_MAX_CHARS,
) -> Dict[str, Any]:
    client = _github_client_instance()
    async with _concurrency_semaphore:
        resp = await client.request(
            method, path, params=params, json=json_body, headers=headers
        )

    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = None
        message = data.get("message") if isinstance(data, dict) else None
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for {method} {path}: "
            f"{message or resp.text}"
        )

    if expect_json:
        try:
            return {"status_code": resp.status_code, "json": resp.json()}
        except Exception:
            return {"status_code": resp.status_code, "json": None}

    return {
        "status_code": resp.status_code,
        "text": resp.text[:text_max_chars],
        "headers": dict(resp.headers),
    }


# ------------------------------------------------------------------------------
# GitHub helpers
# ------------------------------------------------------------------------------


async def _decode_github_content(
    full_name: str,
    path: str,
    ref: str = "main",
) -> Dict[str, Any]:
    data = await _github_request(
        "GET",
        f"/repos/{full_name}/contents/{path}",
        params={"ref": ref},
    )
    if not isinstance(data.get("json"), dict):
        raise GitHubAPIError("Unexpected content response shape from GitHub")

    j = data["json"]
    content = j.get("content")
    encoding = j.get("encoding")
    if encoding == "base64" and isinstance(content, str):
        try:
            decoded_bytes = base64.b64decode(content)
            text = decoded_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise GitHubAPIError(f"Failed to decode file content: {e}")
    else:
        text = ""

    return {
        "status": data["status_code"],
        "text": text,
        "numbered_lines": _with_numbered_lines(text),
        "sha": j.get("sha"),
        "path": j.get("path"),
        "html_url": j.get("html_url"),
    }


async def _get_branch_sha(full_name: str, ref: str) -> str:
    data = await _github_request("GET", f"/repos/{full_name}/git/ref/heads/{ref}")
    j = data["json"]
    if not isinstance(j, dict) or "object" not in j:
        raise GitHubAPIError("Unexpected branch ref response from GitHub")
    return j["object"]["sha"]


async def _resolve_file_sha(full_name: str, path: str, branch: str) -> Optional[str]:
    try:
        decoded = await _decode_github_content(full_name, path, branch)
        return decoded.get("sha")
    except GitHubAPIError:
        return None


async def _perform_github_commit(
    full_name: str,
    path: str,
    message: str,
    body_bytes: bytes,
    branch: str,
    sha: Optional[str],
) -> Dict[str, Any]:
    b64_content = base64.b64encode(body_bytes).decode("ascii")
    payload: Dict[str, Any] = {
        "message": message,
        "content": b64_content,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    result = await _github_request(
        "PUT",
        f"/repos/{full_name}/contents/{path}",
        json_body=payload,
    )
    return result


async def _load_body_from_content_url(content_url: str, *, context: str) -> bytes:
    """Read bytes from a sandbox path, absolute path, or HTTP(S) URL.

    Args:
        content_url: The location of the content to load. Supported formats:
            - ``sandbox:/path`` (preferred when running inside ChatGPT)
            - Absolute file paths (e.g. ``/mnt/data/file``)
            - ``http(s)`` URLs
        context: Name of the calling tool for error messaging.

    Raises:
        ValueError: If the URL is empty.
        GitHubAPIError: If the path cannot be read or the HTTP request fails.
    """

    if not isinstance(content_url, str) or not content_url.strip():
        raise ValueError("content_url must be a non-empty string when provided")

    content_url = content_url.strip()

    def _read_local(local_path: str, missing_hint: str) -> bytes:
        try:
            with open(local_path, "rb") as f:
                return f.read()
        except FileNotFoundError:
            raise GitHubAPIError(
                f"{context} content_url path not found at {local_path}. {missing_hint}"
            )
        except OSError as e:
            raise GitHubAPIError(
                f"Failed to read content_url from {local_path}: {e}"
            )

    async def _fetch_rewritten_path(local_path: str, *, base_url: str) -> bytes:
        rewritten_url = base_url.rstrip("/") + "/" + local_path.lstrip("/")
        client = _external_client_instance()
        response = await client.get(rewritten_url)
        if response.status_code >= 400:
            snippet = response.text[:500]
            raise GitHubAPIError(
                f"Failed to fetch content from rewritten sandbox URL "
                f"{rewritten_url}: {response.status_code}. Response: {snippet}"
            )
        return response.content

    sandbox_hint = (
        "If you are running inside ChatGPT, ensure the file exists in the sandbox "
        "and pass the full sandbox:/ path so the host can rewrite it to an "
        "accessible URL."
    )

    def _is_windows_absolute_path(path: str) -> bool:
        # Match drive-letter paths like ``C:\foo`` or UNC paths like ``\\server``
        return bool(
            re.match(r"^[a-zA-Z]:[\\/].*", path)
            or path.startswith("\\\\")
        )

    # sandbox:/path → local path or optional rewrite via SANDBOX_CONTENT_BASE_URL
    if content_url.startswith("sandbox:"):
        local_path = content_url[len("sandbox:") :]
        rewrite_base = os.environ.get("SANDBOX_CONTENT_BASE_URL")
        try:
            return _read_local(local_path, sandbox_hint)
        except GitHubAPIError:
            if rewrite_base and (
                rewrite_base.startswith("http://") or rewrite_base.startswith("https://")
            ):
                return await _fetch_rewritten_path(local_path, base_url=rewrite_base)
            raise GitHubAPIError(
                f"{context} content_url path not found at {local_path}. "
                "Provide an http(s) URL that already points to the sandbox file "
                "or configure SANDBOX_CONTENT_BASE_URL so the server can fetch it "
                "when direct filesystem access is unavailable."
            )

    # Absolute local path (e.g. /mnt/data/file). If the file is missing, we may
    # still be able to fetch it via a host-provided rewrite base (mirroring the
    # sandbox:/ behavior) so that callers don't need to know whether the
    # runtime supports direct filesystem access.
    if content_url.startswith("/") or _is_windows_absolute_path(content_url):
        rewrite_base = os.environ.get("SANDBOX_CONTENT_BASE_URL")
        missing_hint = (
            "If this was meant to be a sandbox file, prefix it with sandbox:/ so "
            "hosts can rewrite it."
        )
        try:
            return _read_local(content_url, missing_hint)
        except GitHubAPIError:
            if rewrite_base and (
                rewrite_base.startswith("http://") or rewrite_base.startswith("https://")
            ):
                return await _fetch_rewritten_path(content_url, base_url=rewrite_base)
            raise GitHubAPIError(
                f"{context} content_url path not found at {content_url}. "
                f"{missing_hint} Configure SANDBOX_CONTENT_BASE_URL or provide an "
                "absolute http(s) URL so the server can fetch the sandbox file when "
                "it is not mounted locally."
            )

    # Direct http(s) URL
    if content_url.startswith("http://") or content_url.startswith("https://"):
        client = _external_client_instance()
        response = await client.get(content_url)
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"Failed to fetch content from {content_url}: "
                f"{response.status_code}"
            )
        return response.content

    # Anything else is unsupported
    raise GitHubAPIError(
        f"{context} content_url must be an absolute http(s) URL, a sandbox:/ path, "
        "or an absolute local file path. In ChatGPT, pass the sandbox file path "
        "(e.g. sandbox:/mnt/data/file) and the host will rewrite it to a real URL "
        "before it reaches this server."
    )


async def _run_shell(
    cmd: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """Execute a shell command with author/committer env vars injected.

    Stdout and stderr are truncated separately using ``TOOL_STDOUT_MAX_CHARS``
    and ``TOOL_STDERR_MAX_CHARS`` so assistants see the most relevant output
    while keeping responses bounded for the connector UI. Git identity
    environment variables are injected automatically so Git commits made inside
    workspace commands are properly attributed.
    """

    def _truncate_with_marker(text: str, max_chars: int) -> tuple[str, bool]:
        if len(text) <= max_chars:
            return text, False

        marker = "\n... [truncated]"
        if max_chars <= len(marker):
            # Degenerate case when env vars force an extremely small limit
            return marker[:max_chars], True

        head_len = max_chars - len(marker)
        return text[:head_len] + marker, True

    shell_executable = os.environ.get("SHELL")
    if os.name == "nt":
        # Prefer bash when available (e.g., Git Bash) so multi-line commands and
        # POSIX features like heredocs behave consistently across platforms.
        shell_executable = shell_executable or shutil.which("bash")

    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        executable=shell_executable,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": GIT_AUTHOR_NAME,
            "GIT_AUTHOR_EMAIL": GIT_AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": GIT_COMMITTER_NAME,
            "GIT_COMMITTER_EMAIL": GIT_COMMITTER_EMAIL,
        },
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout_seconds
        )
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        stdout_bytes, stderr_bytes = await proc.communicate()
        timed_out = True

    raw_stdout = stdout_bytes.decode("utf-8", errors="replace")
    raw_stderr = stderr_bytes.decode("utf-8", errors="replace")

    stdout, stdout_truncated = _truncate_with_marker(
        raw_stdout, TOOL_STDOUT_MAX_CHARS
    )
    stderr, stderr_truncated = _truncate_with_marker(
        raw_stderr, TOOL_STDERR_MAX_CHARS
    )

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


async def _clone_repo(full_name: str, ref: str = "main") -> str:
    tmpdir = tempfile.mkdtemp(prefix="mcp-github-")
    token = _get_github_token()
    
    url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    cmd = f"git clone --depth 1 --branch {ref} {url} {tmpdir}"
    result = await _run_shell(cmd, cwd=None, timeout_seconds=600)
    if result["exit_code"] != 0:
        stderr = result.get("stderr", "")
        raise GitHubAPIError(f"git clone failed: {stderr}")
    return tmpdir


def _cleanup_dir(path: str) -> None:
    try:
        shutil.rmtree(path)
    except Exception:
        pass


async def _apply_patch_to_repo(repo_dir: str, patch: str) -> None:
    """Write a unified diff to disk and apply it with ``git apply``.

    Assistants should pass the current workspace patch into ``run_command`` or
    ``run_tests`` so the temporary clone mirrors the user's edits. Skipping this
    step is a common cause of repeated test failures that appear unrelated to
    the proposed changes because the command would otherwise execute against the
    untouched remote branch.
    """

    if not patch or not patch.strip():
        raise GitHubAPIError("Received empty patch to apply in workspace")

    patch_path = os.path.join(repo_dir, "mcp_patch.diff")
    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(patch)

    apply_result = await _run_shell(
        f"git apply --whitespace=nowarn {patch_path}",
        cwd=repo_dir,
        timeout_seconds=60,
    )
    if apply_result["exit_code"] != 0:
        stderr = apply_result.get("stderr", "") or apply_result.get("stdout", "")
        raise GitHubAPIError(
            f"git apply failed while preparing workspace: {stderr}"
        )


def _structured_tool_error(
    exc: BaseException, *, context: str, path: Optional[str] = None
) -> Dict[str, Any]:
    """Build a serializable error payload for MCP clients.

    Returning this structure instead of letting exceptions bubble prevents the
    MCP transport layer from wrapping the failure inside generic TaskGroup
    errors, while still surfacing the root cause and traceback to callers.
    """

    import traceback

    error: Dict[str, Any] = {
        "error": exc.__class__.__name__,
        "message": str(exc),
        "context": context,
        "traceback": traceback.format_exc(),
    }
    if path:
        error["path"] = path
    return {"error": error}


# ------------------------------------------------------------------------------
# Write gating and mcp_tool decorator
# ------------------------------------------------------------------------------


def _ensure_write_allowed(context: str) -> None:
    if not WRITE_ALLOWED:
        raise WriteNotAuthorizedError(
            f"MCP write action is temporarily disabled (context: {context})"
        )


def mcp_tool(*, write_action: bool = False, **tool_kwargs):
    """
    Wrapper around FastMCP's @mcp.tool decorator that also tracks whether the
    tool performs write actions via tags/meta instead of mutating the
    FunctionTool object directly (it is a Pydantic model).
    """

    existing_tags = tool_kwargs.pop("tags", None)
    tags: set[str] = set(existing_tags or [])
    if write_action:
        tags.add("write")
    else:
        tags.add("read")

    existing_meta = tool_kwargs.pop("meta", None) or {}
    existing_annotations = tool_kwargs.pop("annotations", None)

    annotations: ToolAnnotations | None
    if isinstance(existing_annotations, ToolAnnotations):
        annotations = existing_annotations
    elif isinstance(existing_annotations, dict):
        annotations = ToolAnnotations(**existing_annotations)
    else:
        annotations = None

    if annotations is None:
        annotations = ToolAnnotations(readOnlyHint=not write_action)
    elif annotations.readOnlyHint is None:
        annotations = annotations.model_copy(update={"readOnlyHint": not write_action})
    if not isinstance(existing_meta, dict):
        existing_meta = {}
    meta = {
        **existing_meta,
        "write_action": write_action,
        # Read-only tools run without extra approval so agents can chain fetches
        # and inspections automatically. Write-tagged tools still require an
        # explicit opt-in via authorize_write_actions or the env flag.
        "auto_approved": not write_action,
    }

    import functools as _functools

    def decorator(func):
        tool = mcp.tool(
            tags=tags or None,
            meta=meta or None,
            annotations=annotations,
            **tool_kwargs,
        )(func)

        if asyncio.iscoroutinefunction(func):

            @_functools.wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs)

        else:

            @_functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)

        wrapper._mcp_tool = tool  # type: ignore[attr-defined]
        return wrapper

    return decorator


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

    global WRITE_ALLOWED
    WRITE_ALLOWED = bool(approved)
    return {"write_allowed": WRITE_ALLOWED}


# ------------------------------------------------------------------------------
# Read-only tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
async def get_server_config() -> Dict[str, Any]:
    """Return a non-sensitive snapshot of connector configuration for assistants.

    Safe to call at the start of a session to understand write gating, HTTP
    timeouts, concurrency limits, log truncation, and sandbox configuration.
    """

    return {
        "write_allowed": WRITE_ALLOWED,
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
        "limits": {
            "stdout_max_chars": TOOL_STDOUT_MAX_CHARS,
            "stderr_max_chars": TOOL_STDERR_MAX_CHARS,
            "logs_max_chars": LOGS_MAX_CHARS,
        },
        "approval_policy": {
            "read_actions": {
                "auto_approved": True,
                "notes": "Read-only tools never require additional approval.",
            },
            "write_actions": {
                "auto_approved": WRITE_ALLOWED,
                "requires_authorization": not WRITE_ALLOWED,
                "toggle_tool": "authorize_write_actions",
                "notes": (
                    "Write-tagged tools stay gated until explicitly enabled for a "
                    "session; set GITHUB_MCP_AUTO_APPROVE to trust the server by "
                    "default."
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
            "sandbox_content_base_url_configured": bool(
                os.environ.get("SANDBOX_CONTENT_BASE_URL")
            ),
        },
        "environment": {
            "github_token_present": bool(
                os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
            ),
        },
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
async def get_profile() -> Dict[str, Any]:
    """Retrieve the authenticated user's GitHub profile."""

    return await _github_request("GET", "/user")


@mcp_tool(write_action=False)
async def get_repo(full_name: str) -> Dict[str, Any]:
    """Fetch repository metadata for ``owner/repo``."""

    return await _github_request("GET", f"/repos/{full_name}")


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
async def fetch_issue(full_name: str, issue_number: int) -> Dict[str, Any]:
    """Fetch a GitHub issue."""

    return await _github_request(
        "GET", f"/repos/{full_name}/issues/{issue_number}"
    )


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

    return await _github_request(
        "GET", f"/repos/{full_name}/commits/{ref}/status"
    )


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
            "name": "commit_file_async",
            "category": "commit",
            "description": "Commit a single file to a branch, optionally using content_url.",
            "notes": "Use for small, targeted changes or external doc commits.",
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
            "name": "apply_patch_and_open_pr",
            "category": "pr+workspace",
            "description": "Apply a unified diff in a clone, optionally run tests, push, and open a PR.",
            "notes": "Primary path for code changes; keep patches small and focused.",
        },
        {
            "name": "run_command",
            "category": "workspace",
            "description": "Clone the repo and run an arbitrary shell command in a temp workspace.",
            "notes": "Use carefully; bound stdout/stderr is returned.",
        },
        {
            "name": "run_tests",
            "category": "workspace",
            "description": "Clone the repo and run tests (default: pytest) in a temp workspace.",
            "notes": "Preferred way to run tests from assistants.",
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

    params = {"per_page": per_page, "page": page}
    return await _github_request("GET", f"/repos/{full_name}/branches", params=params)


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
                results[p] = {"error": str(e)}

    await asyncio.gather(*[_fetch_single(p) for p in paths])
    return {"files": results}


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
    data = await _github_request(
        "GET", f"/repos/{full_name}/git/trees/{ref}", params=params
    )

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
    """Execute a GitHub GraphQL query using the shared HTTP client."""

    client = _github_client_instance()
    payload = {"query": query, "variables": variables or {}}
    async with _concurrency_semaphore:
        resp = await client.post("/graphql", json=payload)

    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub GraphQL error {resp.status_code}: {resp.text}")
    return resp.json()


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch an arbitrary HTTP/HTTPS URL via the shared external client."""

    client = _external_client_instance()
    async with _concurrency_semaphore:
        resp = await client.get(url)
    return {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "content": resp.text[:TOOL_STDOUT_MAX_CHARS],
    }


# ------------------------------------------------------------------------------
# Background read helpers
# ------------------------------------------------------------------------------


def _read_tool_registry() -> Dict[str, Any]:
    """Return a mapping of read-only tool names to their callables.

    The registry is rebuilt on demand so newly imported modules or tools defined
    later in the file are automatically included. Tools tagged as write actions
    are excluded to keep background jobs strictly read-only.
    """

    registry: Dict[str, Any] = {}
    for maybe_func in globals().values():
        tool = getattr(maybe_func, "_mcp_tool", None)
        if tool is None:
            continue
        meta = getattr(tool, "meta", {}) or {}
        if meta.get("write_action"):
            continue
        name = getattr(tool, "name", None) or getattr(maybe_func, "__name__", None)
        if name and name not in {
            "start_background_read",
            "get_background_read",
            "list_background_reads",
        }:
            registry[str(name)] = maybe_func
    return registry


async def _run_background_read(
    job_id: str, tool_name: str, func: Any, arguments: Dict[str, Any]
) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        result = await func(**arguments)
        status = "succeeded"
        error: Optional[Dict[str, Any]] = None
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        result = None
        error = _structured_tool_error(
            exc, context=f"background_read:{tool_name}", path=arguments.get("path")
        )

    finished_at = datetime.now(timezone.utc).isoformat()
    async with _background_read_lock:
        job = _background_read_jobs.get(job_id)
        if job is None:
            return
        recorded_start = job.get("started_at") or started_at
        job.update(
            {
                "status": status,
                "result": result,
                "error": error,
                "started_at": recorded_start,
                "finished_at": finished_at,
            }
        )
        _background_read_tasks.pop(job_id, None)


def _format_background_job(job_id: str, include_result: bool) -> Dict[str, Any]:
    job = _background_read_jobs.get(job_id)
    if not job:
        return {}
    payload: Dict[str, Any] = {
        k: v
        for k, v in job.items()
        if k not in {"task"} and (include_result or k not in {"result", "error"})
    }
    payload["job_id"] = job_id
    return payload


@mcp_tool(write_action=False)
async def start_background_read(
    tool: str, arguments: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Run a read-only tool asynchronously and poll for its result later.

    Background jobs let assistants continue reasoning while long-lived read
    operations (for example large ``fetch_files`` batches) complete. Only tools
    tagged as read actions are eligible; write-tagged tools remain gated.
    """

    registry = _read_tool_registry()
    if tool not in registry:
        raise ValueError(
            f"Unknown or non-read tool '{tool}'. Pick from: {sorted(registry)}"
        )

    args = arguments or {}
    job_id = str(uuid.uuid4())
    job_record = {
        "job_id": job_id,
        "tool": tool,
        "arguments": args,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }

    async with _background_read_lock:
        _background_read_jobs[job_id] = job_record

    task = asyncio.create_task(_run_background_read(job_id, tool, registry[tool], args))
    async with _background_read_lock:
        _background_read_tasks[job_id] = task

    return {"job_id": job_id, "status": "running"}


@mcp_tool(write_action=False)
async def get_background_read(job_id: str, include_result: bool = True) -> Dict[str, Any]:
    """Return status (and optional result) for a background read job."""

    async with _background_read_lock:
        job = _format_background_job(job_id, include_result)

    if not job:
        raise ValueError(f"No background read job found for id {job_id}")
    return job


@mcp_tool(write_action=False)
async def list_background_reads(include_result: bool = False) -> Dict[str, Any]:
    """List tracked background read jobs with optional results."""

    async with _background_read_lock:
        jobs = [
            _format_background_job(job_id, include_result)
            for job_id in list(_background_read_jobs)
        ]

    return {"jobs": jobs}


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
def list_all_actions(include_parameters: bool = False) -> Dict[str, Any]:
    """Enumerate every available MCP tool with read/write metadata.

    This helper exposes a structured catalog of all tools so assistants can see
    the full command surface without reading this file. It is intentionally
    read-only and can therefore be called before write approval is granted.

    Args:
        include_parameters: When ``True``, include the serialized input schema
            for each tool to clarify argument names and types.
    """

    tools: List[Dict[str, Any]] = []
    for maybe_func in globals().values():
        tool = getattr(maybe_func, "_mcp_tool", None)
        if tool is None:
            continue

        meta = getattr(tool, "meta", {}) or {}
        annotations = getattr(tool, "annotations", None)

        name = getattr(tool, "name", None) or getattr(maybe_func, "__name__", None)
        description = getattr(tool, "description", None) or (maybe_func.__doc__ or "")

        tool_info: Dict[str, Any] = {
            "name": str(name),
            "description": description.strip(),
            "tags": sorted(list(getattr(tool, "tags", []) or [])),
            "write_action": bool(meta.get("write_action")),
            "auto_approved": bool(meta.get("auto_approved")),
            "read_only_hint": getattr(annotations, "readOnlyHint", None),
        }

        if include_parameters:
            schema = getattr(tool, "inputSchema", None)
            if schema is not None:
                try:
                    tool_info["input_schema"] = schema.model_dump()
                except Exception:
                    tool_info["input_schema"] = None

        tools.append(tool_info)

    tools.sort(key=lambda entry: entry["name"])

    return {
        "write_actions_enabled": WRITE_ALLOWED,
        "tools": tools,
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

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/actions/runs/{run_id}/jobs",
        params=params,
    )


@mcp_tool(write_action=False)
async def get_job_logs(full_name: str, job_id: int) -> Dict[str, Any]:
    """Fetch raw logs for a GitHub Actions job, truncated to ``LOGS_MAX_CHARS``."""

    client = _github_client_instance()
    request = client.build_request(
        "GET",
        f"/repos/{full_name}/actions/jobs/{job_id}/logs",
    )
    async with _concurrency_semaphore:
        resp = await client.send(request, follow_redirects=True)
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub job logs error {resp.status_code}: {resp.text}"
        )
    content_type = resp.headers.get("Content-Type", "")
    if "zip" in content_type.lower():
        logs = _decode_zipped_job_logs(resp.content)
    else:
        logs = resp.text

    return {
        "status_code": resp.status_code,
        "logs": logs[:LOGS_MAX_CHARS],
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
            raise GitHubAPIError(
                f"GitHub workflow run error {resp.status_code}: {resp.text}"
            )

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


@mcp_tool(write_action=True)
async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Trigger a workflow dispatch event on the given ref."""

    _ensure_write_allowed(f"trigger workflow {workflow} on {full_name}@{ref}")
    payload = {"ref": ref}
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

    result = await wait_for_workflow_run(
        full_name, run_id, timeout_seconds, poll_interval_seconds
    )
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
    """List pull requests with optional head/base filters."""

    params: Dict[str, Any] = {
        "state": state,
        "per_page": per_page,
        "page": page,
    }
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
    """Merge a pull request using squash (default), merge, or rebase."""

    _ensure_write_allowed(f"merge PR #{number} in {full_name}")
    payload: Dict[str, Any] = {"merge_method": merge_method}
    if commit_title is not None:
        payload["commit_title"] = commit_title
    if commit_message is not None:
        payload["commit_message"] = commit_message
    return await _github_request(
        "PUT",
        f"/repos/{full_name}/pulls/{number}/merge",
        json_body=payload,
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
    trimmed_files = []
    for f in files[:100]:
        patch = f.get("patch")
        if isinstance(patch, str) and len(patch) > 8000:
            patch = patch[:8000] + "\n... [truncated]"
        trimmed_files.append({**f, "patch": patch})
    j["files"] = trimmed_files
    return j


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
        raise GitHubAPIError(
            f"GitHub ensure_branch error {resp.status_code}: {resp.text}"
        )
    return {"status_code": resp.status_code, "json": resp.json()}


@mcp_tool(write_action=True)
async def commit_file_async(
    full_name: str,
    path: str,
    message: str,
    content: Optional[str] = None,
    *,
    content_url: Optional[str] = None,
    branch: str = "main",
    sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Schedule a single file commit in the background."""

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    _ensure_write_allowed(f"commit file async {path}")

    print(
        "[commit_file_async] scheduling full_name=%r path=%r branch=%r "
        "message=%r has_content=%s content_url=%r sha=%r"
        % (full_name, path, branch, message, content is not None, content_url, sha)
    )

    if content is None and content_url is None:
        raise ValueError("Either content or content_url must be provided")
    if content is not None and content_url is not None:
        raise ValueError("Provide content or content_url, but not both")

    if content_url is not None:
        body_bytes = await _load_body_from_content_url(
            content_url, context="commit_file_async"
        )
    else:
        body_bytes = content.encode("utf-8")

    if sha is None:
        sha = await _resolve_file_sha(full_name, path, branch)

    async def _do_commit() -> None:
        try:
            await _perform_github_commit(
                full_name=full_name,
                path=path,
                message=message,
                body_bytes=body_bytes,
                branch=branch,
                sha=sha,
            )
            print(f"[commit_file_async] commit completed for {full_name}/{path}")
        except Exception as e:
            print(f"[commit_file_async] commit failed for {full_name}/{path}: {e}")

    asyncio.create_task(_do_commit())

    return {
        "scheduled": True,
        "path": path,
        "branch": branch,
        "message": message,
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
    """Open a pull request from ``head`` into ``base``."""

    _ensure_write_allowed(f"create PR from {head} to {base} in {full_name}")
    payload: Dict[str, Any] = {
        "title": title,
        "head": head,
        "base": base,
        "draft": draft,
    }
    if body is not None:
        payload["body"] = body

    return await _github_request(
        "POST",
        f"/repos/{full_name}/pulls",
        json_body=payload,
    )


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
    """Commit multiple files then open a PR in one call."""

    current_path: Optional[str] = None
    try:
        _ensure_write_allowed(f"update_files_and_open_pr {full_name} {title}")

        branch = new_branch or f"ally-{os.urandom(4).hex()}"
        await ensure_branch(full_name, branch, from_ref=base_branch)

        for f in files:
            current_path = f["path"]
            file_message = f.get("message") or title
            content = f.get("content")
            content_url = f.get("content_url")

            if content is None and content_url is None:
                raise ValueError(
                    f"File entry for {current_path} must have content or content_url"
                )
            if content is not None and content_url is not None:
                raise ValueError(
                    f"File entry for {current_path} must not provide both content "
                    "and content_url"
                )

            try:
                if content_url is not None:
                    body_bytes = await _load_body_from_content_url(
                        content_url, context="update_files_and_open_pr"
                    )
                else:
                    body_bytes = content.encode("utf-8")
            except Exception as exc:
                return _structured_tool_error(
                    exc, context="update_files_and_open_pr.load_content", path=current_path
                )

            try:
                sha = await _resolve_file_sha(full_name, current_path, branch)
                await _perform_github_commit(
                    full_name=full_name,
                    path=current_path,
                    message=file_message,
                    body_bytes=body_bytes,
                    branch=branch,
                    sha=sha,
                )
            except Exception as exc:
                return _structured_tool_error(
                    exc,
                    context="update_files_and_open_pr.commit_file",
                    path=current_path,
                )

        try:
            pr = await create_pull_request(
                full_name=full_name,
                title=title,
                head=branch,
                base=base_branch,
                body=body,
                draft=draft,
            )
        except Exception as exc:
            return _structured_tool_error(
                exc, context="update_files_and_open_pr.create_pr", path=current_path
            )
        return {"branch": branch, "pull_request": pr}
    except Exception as exc:
        return _structured_tool_error(
            exc, context="update_files_and_open_pr", path=current_path
        )


# ------------------------------------------------------------------------------
# Workspace / full-environment tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=True)
async def run_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
) -> Dict[str, Any]:
    """Clone the repository and run an arbitrary shell command in a temp dir.

    Args:
        full_name: GitHub repository in ``owner/name`` format.
        ref: Branch, tag, or commit to check out. Defaults to ``main``.
        command: Shell command to execute inside the clone.
        timeout_seconds: Hard timeout applied to the command execution.
        workdir: Optional path inside the repository to use as the working
            directory.
        patch: Optional unified diff that will be applied before running the
            command so assistants can run tests against in-flight edits.

    The temporary directory is cleaned up automatically after execution, so
    callers should capture any artifacts they need from ``result.stdout`` or by
    writing to remote destinations during the command itself.
    """

    repo_dir: Optional[str] = None
    try:
        _ensure_write_allowed(f"run_command {command} in {full_name}@{ref}")
        repo_dir = await _clone_repo(full_name, ref=ref)

        if patch:
            await _apply_patch_to_repo(repo_dir, patch)

        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)
        result = await _run_shell(command, cwd=cwd, timeout_seconds=timeout_seconds)
        return {
            "repo_dir": repo_dir,
            "workdir": workdir,
            "result": result,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="run_command")
    finally:
        if repo_dir:
            _cleanup_dir(repo_dir)


@mcp_tool(write_action=True)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the project's test command after cloning into a temp workspace.

    ``run_tests`` is a thin wrapper around ``run_command`` with a more explicit
    default timeout. Provide ``patch`` when running tests against pending edits
    so the checkout matches the assistant's current working diff.
    """
    return await run_command(
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        patch=patch,
    )


@mcp_tool(write_action=True)
async def apply_patch_and_open_pr(
    full_name: str,
    base_branch: str,
    patch: str,
    title: str,
    body: Optional[str] = None,
    new_branch: Optional[str] = None,
    run_tests_flag: bool = False,
    test_command: str = "pytest",
    test_timeout_seconds: int = 600,
    draft: bool = False,
) -> Dict[str, Any]:
    """Apply a unified diff, optionally run tests, push, and open a PR."""

    _ensure_write_allowed(f"apply_patch_and_open_pr on {full_name}@{base_branch}")

    # Guardrail: do not proceed on empty / whitespace-only patches.
    if not patch or not patch.strip():
        return {
            "branch": None,
            "tests": None,
            "pull_request": None,
            "error": "empty_patch",
            "stderr": "apply_patch_and_open_pr: received empty or whitespace-only patch",
        }

    branch = new_branch or f"ally-patch-{os.urandom(4).hex()}"
    repo_dir = await _clone_repo(full_name, ref=base_branch)
    tests_result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_stderr: Optional[str] = None

    try:
        checkout_result = await _run_shell(
            f"git checkout -b {branch}",
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if checkout_result["exit_code"] != 0:
            error = "git_checkout_failed"
            error_stderr = checkout_result.get("stderr", "")
            return {
                "branch": branch,
                "tests": tests_result,
                "pull_request": None,
                "error": error,
                "stderr": error_stderr,
            }

        patch_path = os.path.join(repo_dir, "mcp_patch.diff")
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(patch)

        apply_result = await _run_shell(
            f"git apply --whitespace=nowarn {patch_path}",
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if apply_result["exit_code"] != 0:
            error = "git_apply_failed"
            error_stderr = apply_result.get("stderr", "")
            return {
                "branch": branch,
                "tests": tests_result,
                "pull_request": None,
                "error": error,
                "stderr": error_stderr,
            }

        try:
            os.remove(patch_path)
        except OSError:
            pass

        add_result = await _run_shell(
            "git add -A",
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if add_result["exit_code"] != 0:
            error = "git_add_failed"
            error_stderr = add_result.get("stderr", "") or add_result.get(
                "stdout", ""
            )
            return {
                "branch": branch,
                "tests": tests_result,
                "pull_request": None,
                "error": error,
                "stderr": error_stderr,
            }

        diff_result = await _run_shell(
            "git diff --cached --stat",
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if diff_result["exit_code"] != 0:
            error = "git_diff_failed"
            error_stderr = diff_result.get("stderr", "") or diff_result.get(
                "stdout", ""
            )
            return {
                "branch": branch,
                "tests": tests_result,
                "pull_request": None,
                "error": error,
                "stderr": error_stderr,
            }

        if not diff_result.get("stdout", "").strip():
            return {
                "branch": branch,
                "tests": tests_result,
                "pull_request": None,
                "error": "empty_diff",
                "stderr": "apply_patch_and_open_pr: patch applied but no changes to commit",
            }

        commit_result = await _run_shell(
            f'git commit -am "{title}"',
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if commit_result["exit_code"] != 0:
            error = "git_commit_failed"
            error_stderr = commit_result.get("stderr", "") or commit_result.get(
                "stdout", ""
            )
            return {
                "branch": branch,
                "tests": tests_result,
                "pull_request": None,
                "error": error,
                "stderr": error_stderr,
            }

        if run_tests_flag:
            tests_result = await _run_shell(
                test_command,
                cwd=repo_dir,
                timeout_seconds=test_timeout_seconds,
            )
            if tests_result["exit_code"] != 0 or tests_result["timed_out"]:
                error = "tests_failed"
                return {
                    "branch": branch,
                    "tests": tests_result,
                    "pull_request": None,
                    "error": error,
                    "stderr": tests_result.get("stderr", ""),
                }

        token = _get_github_token()

        push_url = f"https://x-access-token:{token}@github.com/{full_name}.git"
        push_result = await _run_shell(
            f"git push {push_url} {branch}",
            cwd=repo_dir,
            timeout_seconds=300,
        )
        if push_result["exit_code"] != 0:
            error = "git_push_failed"
            error_stderr = push_result.get("stderr", "")
            return {
                "branch": branch,
                "tests": tests_result,
                "pull_request": None,
                "error": error,
                "stderr": error_stderr,
            }

        pr = await create_pull_request(
            full_name=full_name,
            title=title,
            head=branch,
            base=base_branch,
            body=body,
            draft=draft,
        )

        return {
            "branch": branch,
            "tests": tests_result,
            "pull_request": pr,
            "error": None,
            "stderr": None,
        }
    finally:
        _cleanup_dir(repo_dir)


# ------------------------------------------------------------------------------
# FastMCP HTTP/SSE app and health routes
# ------------------------------------------------------------------------------

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


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK\n")


async def _shutdown_clients() -> None:
    if _http_client_github is not None:
        await _http_client_github.aclose()
    if _http_client_external is not None:
        await _http_client_external.aclose()


app.add_event_handler("shutdown", _shutdown_clients)
