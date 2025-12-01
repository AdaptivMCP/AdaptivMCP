"""GitHub MCP server exposing connector-friendly tools and workflows.

This module is the entry point for the GitHub Model Context Protocol server
used by ChatGPT connectors. It lists the tools, arguments, and behaviors in a
single place so an assistant can decide how to interact with the server without
being pushed toward a particular working style. See ``docs/WORKFLOWS.md`` and ``docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md``
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
import difflib
import sys
import logging
import time
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from anyio import ClosedResourceError
from mcp.types import ToolAnnotations
from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
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

GIT_AUTHOR_NAME = os.environ.get("GIT_AUTHOR_NAME", "Ally")

# Upper bounds for tool stdout/stderr payloads returned to the connector. These
# can be tuned via environment variables; set to 0 or a negative value to disable
# truncation if a deployment prefers full logs at the cost of larger responses.
TOOL_STDOUT_MAX_CHARS = int(os.environ.get("TOOL_STDOUT_MAX_CHARS", "12000"))
TOOL_STDERR_MAX_CHARS = int(os.environ.get("TOOL_STDERR_MAX_CHARS", "6000"))
GIT_AUTHOR_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "ally@example.com")
GIT_COMMITTER_NAME = os.environ.get("GIT_COMMITTER_NAME", GIT_AUTHOR_NAME)
GIT_COMMITTER_EMAIL = os.environ.get("GIT_COMMITTER_EMAIL", GIT_AUTHOR_EMAIL)


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


def _new_metrics_state() -> Dict[str, Any]:
    return {
        "tools": {},
        "github": {
            "requests_total": 0,
            "errors_total": 0,
            "rate_limit_events_total": 0,
            "timeouts_total": 0,
        },
    }


_METRICS: Dict[str, Any] = _new_metrics_state()


def _reset_metrics_for_tests() -> None:
    """Reset in-process metrics; intended for tests."""

    global _METRICS
    _METRICS = _new_metrics_state()


def _record_tool_call(
    tool_name: str,
    *,
    write_action: bool,
    duration_ms: int,
    errored: bool,
) -> None:
    tools_bucket = _METRICS.setdefault("tools", {})
    bucket = tools_bucket.setdefault(
        tool_name,
        {
            "calls_total": 0,
            "errors_total": 0,
            "write_calls_total": 0,
            "latency_ms_sum": 0,
        },
    )
    bucket["calls_total"] += 1
    if write_action:
        bucket["write_calls_total"] += 1
    bucket["latency_ms_sum"] += max(0, int(duration_ms))
    if errored:
        bucket["errors_total"] += 1


def _record_github_request(
    *,
    status_code: Optional[int],
    duration_ms: int,
    error: bool,
    resp: Optional[httpx.Response] = None,
    exc: Optional[BaseException] = None,
) -> None:
    github_bucket = _METRICS.setdefault("github", {})
    github_bucket["requests_total"] = github_bucket.get("requests_total", 0) + 1
    if error:
        github_bucket["errors_total"] = github_bucket.get("errors_total", 0) + 1

    if resp is not None:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                if int(remaining) <= 0:
                    github_bucket["rate_limit_events_total"] = github_bucket.get(
                        "rate_limit_events_total", 0
                    ) + 1
            except ValueError:
                pass

    if exc is not None and isinstance(exc, httpx.TimeoutException):
        github_bucket["timeouts_total"] = github_bucket.get(
            "timeouts_total", 0
        ) + 1




def _metrics_snapshot() -> Dict[str, Any]:
    """Return a shallow, JSON-safe snapshot of in-process metrics.

    The metrics registry is intentionally small and numeric, but this helper
    defensively normalizes missing buckets and coerces values to ``int`` where
    possible so that the health payload remains stable even if future fields are
    added.
    """

    tools = _METRICS.get("tools", {})
    github = _METRICS.get("github", {})

    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:  # pragma: no cover - defensive
            return default

    return {
        "tools": tools,
        "github": {k: _as_int(v) for k, v in github.items()},
    }
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

CONTROLLER_REPO = os.environ.get(
    "GITHUB_MCP_CONTROLLER_REPO", "Proofgate-Revocations/chatgpt-mcp-github"
)

# Machine-readable contract version for controllers and assistants. This helps
# keep prompts, workflows, and server behavior aligned as they evolve.
CONTROLLER_CONTRACT_VERSION = os.environ.get(
    "GITHUB_MCP_CONTROLLER_CONTRACT_VERSION", "2025-03-08"
)
CONTROLLER_DEFAULT_BRANCH = os.environ.get(
    "GITHUB_MCP_CONTROLLER_BRANCH", "main"
)


def _effective_ref_for_repo(full_name: str, ref: Optional[str]) -> str:
    """Resolve the effective Git ref for a repository."""

    if full_name == CONTROLLER_REPO:
        if not ref or ref == "main":
            return CONTROLLER_DEFAULT_BRANCH
        return ref
    return ref or "main"


def _with_numbered_lines(text: str) -> List[Dict[str, Any]]:
    """Return a list of dicts pairing 1-based line numbers with text."""

    return [{"line": idx, "text": line} for idx, line in enumerate(text.splitlines(), 1)]


def _render_visible_whitespace(text: str) -> str:
    """Surface whitespace characters for assistants that hide them by default."""

    rendered_lines: List[str] = []
    for line in text.splitlines(keepends=True):
        body = line[:-1] if line.endswith("\n") else line
        body = body.replace("\t", "→\t").replace(" ", "·")
        newline_marker = "⏎" if line.endswith("\n") else "␄"
        rendered_lines.append(f"{body}{newline_marker}")

    return "\n".join(rendered_lines)


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
    raw_token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if raw_token is None:
        raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN must be set")

    token = raw_token.strip()
    if not token:
        raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN is empty or whitespace")

    # Preserve the original value in the environment to avoid surprising callers
    # while ensuring outbound requests use the cleaned token.
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
    text_max_chars: Optional[int] = None,
) -> Dict[str, Any]:
    client = _github_client_instance()
    started_at = time.monotonic()
    try:
        async with _concurrency_semaphore:
            resp = await client.request(
                method, path, params=params, json=json_body, headers=headers
            )
    except Exception as exc:  # pragma: no cover - defensive
        duration_ms = int((time.monotonic() - started_at) * 1000)
        _record_github_request(
            status_code=None,
            duration_ms=duration_ms,
            error=True,
            resp=None,
            exc=exc,
        )
        GITHUB_LOGGER.error(
            "github_request_error",
            extra={
                "event": "github_request",
                "method": method,
                "path": path,
                "status_code": None,
                "duration_ms": duration_ms,
                "error": type(exc).__name__,
            },
            exc_info=True,
        )
        raise

    duration_ms = int((time.monotonic() - started_at) * 1000)
    base_payload = {
        "event": "github_request",
        "method": method,
        "path": path,
        "status_code": resp.status_code,
        "duration_ms": duration_ms,
        "rate_limit": {
            "limit": resp.headers.get("X-RateLimit-Limit"),
            "remaining": resp.headers.get("X-RateLimit-Remaining"),
            "reset": resp.headers.get("X-RateLimit-Reset"),
        },
    }

    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = None
        message = data.get("message") if isinstance(data, dict) else None
        error_payload = dict(base_payload)
        error_payload["error"] = "http_error"
        # Truncate to avoid huge log records on large error bodies.
        error_payload["error_message"] = (message or resp.text[:500])

        _record_github_request(
            status_code=resp.status_code,
            duration_ms=duration_ms,
            error=True,
            resp=resp,
            exc=None,
        )

        if resp.status_code in {401, 403}:
            error_payload["error"] = "github_auth_error"
            GITHUB_LOGGER.warning("github_auth_error", extra=error_payload)
            raise GitHubAuthError(
                "GitHub authentication failed "
                f"({resp.status_code}) for {method} {path}: "
                f"{message or resp.text} -- ensure GITHUB_PAT or GITHUB_TOKEN is set "
                "with the necessary scopes for search and repository access"
            )

        GITHUB_LOGGER.warning("github_request_error", extra=error_payload)
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for {method} {path}: "
            f"{message or resp.text}"
        )

    _record_github_request(
        status_code=resp.status_code,
        duration_ms=duration_ms,
        error=False,
        resp=resp,
        exc=None,
    )
    GITHUB_LOGGER.info("github_request", extra=base_payload)

    if expect_json:
        try:
            return {"status_code": resp.status_code, "json": resp.json()}
        except Exception:
            return {"status_code": resp.status_code, "json": None}

    text = resp.text if text_max_chars is None else resp.text[:text_max_chars]
    return {
        "status_code": resp.status_code,
        "text": text,
        "headers": dict(resp.headers),
    }


# ------------------------------------------------------------------------------
# GitHub helpers
# ------------------------------------------------------------------------------

async def _verify_file_on_branch(
    full_name: str,
    path: str,
    branch: str,
) -> Dict[str, Any]:
    """Verify that a file exists on a specific branch after a write.

    This helper is used by higher-level orchestration tools to insert an
    explicit verification step between committing changes and opening a PR.

    Returns a small JSON-friendly payload summarizing the verification result.
    Raises GitHubAPIError if the file cannot be fetched.
    """
    try:
        decoded = await _decode_github_content(full_name, path, branch)
    except Exception as exc:  # pragma: no cover - defensive
        raise GitHubAPIError(
            f"Post-commit verification failed for {full_name}/{path}@{branch}: {exc}"
        ) from exc

    text = decoded.get("text", "")
    return {
        "full_name": full_name,
        "path": path,
        "branch": branch,
        "verified": True,
        "size": len(text) if isinstance(text, str) else None,
    }


async def _decode_github_content(
    full_name: str,
    path: str,
    ref: Optional[str] = None,
) -> Dict[str, Any]:
    effective_ref = _effective_ref_for_repo(full_name, ref)
    try:
        data = await _github_request(
            "GET",
            f"/repos/{full_name}/contents/{path}",
            params={"ref": effective_ref},
        )
    except GitHubAPIError as exc:
        raise GitHubAPIError(
            f"Failed to fetch {full_name}/{path} at ref '{effective_ref}': {exc}"
        ) from exc
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
    effective_ref = _effective_ref_for_repo(full_name, ref)
    data = await _github_request(
        "GET", f"/repos/{full_name}/git/ref/heads/{effective_ref}"
    )
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
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Execute a shell command with author/committer env vars injected.

    Git identity environment variables are injected automatically so Git commits
    made inside workspace commands are properly attributed. Outputs are returned
    in full to preserve complete context for downstream tools and assistants.
    """

    shell_executable = os.environ.get("SHELL")
    if os.name == "nt":
        # Prefer bash when available (e.g., Git Bash) so multi-line commands and
        # POSIX features like heredocs behave consistently across platforms.
        shell_executable = shell_executable or shutil.which("bash")

    proc_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": GIT_AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": GIT_AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": GIT_COMMITTER_NAME,
        "GIT_COMMITTER_EMAIL": GIT_COMMITTER_EMAIL,
    }
    if env is not None:
        proc_env.update(env)

    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        executable=shell_executable,
        env=proc_env,
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
    stdout = raw_stdout
    stderr = raw_stderr
    stdout_truncated = False
    stderr_truncated = False

    if (
        TOOL_STDOUT_MAX_CHARS
        and TOOL_STDOUT_MAX_CHARS > 0
        and len(stdout) > TOOL_STDOUT_MAX_CHARS
    ):
        stdout = stdout[:TOOL_STDOUT_MAX_CHARS]
        stdout_truncated = True

    if (
        TOOL_STDERR_MAX_CHARS
        and TOOL_STDERR_MAX_CHARS > 0
        and len(stderr) > TOOL_STDERR_MAX_CHARS
    ):
        stderr = stderr[:TOOL_STDERR_MAX_CHARS]
        stderr_truncated = True

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }
async def _clone_repo(full_name: str, ref: Optional[str] = None) -> str:
    tmpdir = tempfile.mkdtemp(prefix="mcp-github-")
    token = _get_github_token()

    effective_ref = _effective_ref_for_repo(full_name, ref)
    url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    cmd = f"git clone --depth 1 --branch {effective_ref} {url} {tmpdir}"
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


async def _prepare_temp_virtualenv(repo_dir: str) -> Dict[str, str]:
    """Create an isolated virtualenv and return env vars that activate it."""

    venv_dir = os.path.join(repo_dir, ".venv-mcp")
    result = await _run_shell(
        f"{sys.executable} -m venv {venv_dir}",
        cwd=repo_dir,
        timeout_seconds=300,
    )
    if result["exit_code"] != 0:
        stderr = result.get("stderr", "") or result.get("stdout", "")
        raise GitHubAPIError(f"Failed to create temp virtualenv: {stderr}")

    bin_dir = "Scripts" if os.name == "nt" else "bin"
    bin_path = os.path.join(venv_dir, bin_dir)
    return {
        "VIRTUAL_ENV": venv_dir,
        "PATH": f"{bin_path}{os.pathsep}" + os.environ.get("PATH", ""),
    }


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

# Global registry of MCP tools, populated by the mcp_tool decorator. This lets
# us enumerate tools defined in other modules (for example extra_tools.py) as
# long as they are decorated with the shared mcp_tool wrapper.
_REGISTERED_MCP_TOOLS: list[tuple[Any, Any]] = []

def mcp_tool(*, write_action: bool = False, **tool_kwargs):
    """Wrapper around FastMCP's @mcp.tool decorator.

    The decorator:
    * Adds ``read``/``write`` tags and ToolAnnotations.readOnlyHint.
    * Attaches a ``write_action`` flag and ``auto_approved`` hint to meta.
    * Registers the tool in a global registry for discovery.
    * Emits structured logs around tool execution so operators can trace
      behavior without logging full argument or result payloads.
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
    import inspect as _inspect

    def decorator(func):
        tool = mcp.tool(
            tags=tags or None,
            meta=meta or None,
            annotations=annotations,
            **tool_kwargs,
        )(func)

        # Resolve the function signature once so we can build a coarse argument
        # map for logging without serializing full payloads.
        try:
            signature = _inspect.signature(func)
        except (TypeError, ValueError):
            signature = None

        def _extract_call_context(args, **kwargs):
            """Return coarse, non-sensitive context for logging purposes."""
            all_args: Dict[str, Any] = {}

            if signature is not None:
                try:
                    bound = signature.bind_partial(*args, **kwargs)
                    all_args = dict(bound.arguments)
                except Exception:
                    # Fall back to kwargs-only mapping if binding fails.
                    all_args = {}

            if not all_args:
                # Ignore positional arguments in the fallback path so we never
                # accidentally log large payloads or opaque binary blobs.
                all_args = dict(kwargs)

            repo_full_name: Optional[str] = None
            if isinstance(all_args.get("full_name"), str):
                repo_full_name = all_args["full_name"]
            elif isinstance(all_args.get("owner"), str) and isinstance(
                all_args.get("repo"), str
            ):
                repo_full_name = f"{all_args['owner']}/{all_args['repo']}"

            ref: Optional[str] = None
            for key in ("ref", "branch", "base_ref", "head_ref"):
                value = all_args.get(key)
                if isinstance(value, str):
                    ref = value
                    break

            path: Optional[str] = None
            for key in ("path", "file_path"):
                value = all_args.get(key)
                if isinstance(value, str):
                    path = value
                    break

            arg_keys = sorted(set(all_args.keys()))
            return {
                "repo": repo_full_name,
                "ref": ref,
                "path": path,
                "arg_keys": arg_keys,
            }

        def _result_size_hint(result: Any) -> Optional[int]:
            if isinstance(result, (list, tuple, str)):
                return len(result)
            if isinstance(result, dict):
                return len(result)
            return None

        if asyncio.iscoroutinefunction(func):

            @_functools.wraps(func)
            async def wrapper(*args, **kwargs):
                call_id = str(uuid.uuid4())
                context = _extract_call_context(args, **kwargs)
                start = time.perf_counter()

                TOOLS_LOGGER.info(
                    "tool_call_start",
                    extra={
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                    },
                )

                errored = False
                try:
                    result = await func(*args, **kwargs)
                except Exception as exc:
                    errored = True
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_tool_call(
                        tool_name=tool.name,
                        write_action=write_action,
                        duration_ms=duration_ms,
                        errored=True,
                    )
                    TOOLS_LOGGER.exception(
                        "tool_call_error",
                        extra={
                            "tool_name": tool.name,
                            "write_action": write_action,
                            "tags": sorted(tags) if tags else [],
                            "call_id": call_id,
                            "repo": context["repo"],
                            "ref": context["ref"],
                            "path": context["path"],
                            "arg_keys": context["arg_keys"],
                            "duration_ms": duration_ms,
                            "status": "error",
                            "error_type": exc.__class__.__name__,
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(
                    tool_name=tool.name,
                    write_action=write_action,
                    duration_ms=duration_ms,
                    errored=errored,
                )
                TOOLS_LOGGER.info(
                    "tool_call_success",
                    extra={
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                        "duration_ms": duration_ms,
                        "status": "ok",
                        "result_type": type(result).__name__,
                        "result_size_hint": _result_size_hint(result),
                    },
                )
                return result

        else:

            @_functools.wraps(func)
            def wrapper(*args, **kwargs):
                call_id = str(uuid.uuid4())
                context = _extract_call_context(args, **kwargs)
                start = time.perf_counter()

                TOOLS_LOGGER.info(
                    "tool_call_start",
                    extra={
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                    },
                )

                errored = False
                try:
                    result = func(*args, **kwargs)
                except Exception as exc:
                    errored = True
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    _record_tool_call(
                        tool_name=tool.name,
                        write_action=write_action,
                        duration_ms=duration_ms,
                        errored=True,
                    )
                    TOOLS_LOGGER.exception(
                        "tool_call_error",
                        extra={
                            "tool_name": tool.name,
                            "write_action": write_action,
                            "tags": sorted(tags) if tags else [],
                            "call_id": call_id,
                            "repo": context["repo"],
                            "ref": context["ref"],
                            "path": context["path"],
                            "arg_keys": context["arg_keys"],
                            "duration_ms": duration_ms,
                            "status": "error",
                            "error_type": exc.__class__.__name__,
                        },
                    )
                    raise

                duration_ms = int((time.perf_counter() - start) * 1000)
                _record_tool_call(
                    tool_name=tool.name,
                    write_action=write_action,
                    duration_ms=duration_ms,
                    errored=errored,
                )
                TOOLS_LOGGER.info(
                    "tool_call_success",
                    extra={
                        "tool_name": tool.name,
                        "write_action": write_action,
                        "tags": sorted(tags) if tags else [],
                        "call_id": call_id,
                        "repo": context["repo"],
                        "ref": context["ref"],
                        "path": context["path"],
                        "arg_keys": context["arg_keys"],
                        "duration_ms": duration_ms,
                        "status": "ok",
                        "result_type": type(result).__name__,
                        "result_size_hint": _result_size_hint(result),
                    },
                )
                return result

        # Attach the underlying FastMCP tool object so other helpers can inspect
        # metadata, and register the tool in the global registry so we can
        # enumerate tools defined in other modules.
        wrapper._mcp_tool = tool  # type: ignore[attr-defined]
        _REGISTERED_MCP_TOOLS.append((tool, wrapper))
        return wrapper

    return decorator


# ------------------------------------------------------------------------------
# Optional dynamic tool registration (extra_tools.py)
# ------------------------------------------------------------------------------

try:
    # If extra_tools.py exists and exposes register_extra_tools, use it
    # to register additional tools using the same mcp_tool decorator.
    from extra_tools import register_extra_tools  # type: ignore[import]
except Exception:
    register_extra_tools = None  # type: ignore[assignment]

if callable(register_extra_tools):
    try:
        # Pass the decorator so extra_tools.py can define new tools without
        # importing main.py directly.
        register_extra_tools(mcp_tool)
    except Exception:
        # Extension tools are strictly optional; never break the core server
        # if extension registration fails for any reason.
        pass

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
    timeouts, concurrency limits, and sandbox configuration.
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
        return {
            "valid": False,
            "error": exc.msg,
            "line": exc.lineno,
            "column": exc.colno,
            "position": exc.pos,
            "snippet": raw[start:end],
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
        try:
            await _github_request("GET", f"/repos/{controller_repo}")
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

        try:
            await _github_request("GET", f"/repos/{controller_repo}/branches/{controller_branch}")
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
def controller_contract() -> Dict[str, Any]:
    """Return the controller/assistant contract in a structured format.

    This payload is meant to reduce misunderstandings between controller
    prompts, assistants, and the MCP server. Controllers can surface it to
    ChatGPT to remind the assistant which workflows are expected and how writes
    are gated.
    """

    return {
        "version": CONTROLLER_CONTRACT_VERSION,
        "summary": "Contract describing how controllers, assistants, and this GitHub MCP server work together.",
        "controller": {
            "repo": CONTROLLER_REPO,
            "default_branch": CONTROLLER_DEFAULT_BRANCH,
            "write_allowed_default": WRITE_ALLOWED,
        },
        "expectations": {
            "assistant": [
                "Treat run_command and run_tests as the canonical execution paths; do not assume packages are installed in the MCP server process.",
                "Favor branch-first workflows and avoid writing to main for the controller repo unless explicitly told otherwise.",
                "Keep writes disabled until authorize_write_actions approves them and explain when a write is blocked.",
                "Summarize what changed and which tools ran so humans can audit actions easily.",
                "Verify outputs and state before repeating actions so runs do not get stuck in loops; report blockers clearly.",
                "Use get_file_slice and diff helpers for large files instead of shuttling entire files; validate long JSON payloads before sending.",
            ],
            "controller_prompt": [
                "Call get_server_config early to learn write_allowed, HTTP limits, and controller defaults.",
                "Encourage use of list_write_tools and validate_environment so the assistant knows available tools and common pitfalls.",
                "Steer assistants toward update_files_and_open_pr or apply_patch_and_commit instead of low-level Git operations.",
                "Nudge assistants toward large-file helpers like get_file_slice, build_section_based_diff, and validate_json_string to avoid retries and token blowups.",
            ],
            "server": [
                "Reject write tools when WRITE_ALLOWED is false and surface clear errors for controllers to relay.",
                "Default to the configured controller branch when refs are missing for the controller repo to reduce accidental writes to main.",
                "Expose minimal health and metrics data so controllers can debug without extra API calls.",
            ],
        },
        "tooling": {
            "discovery": ["get_server_config", "list_write_tools", "validate_environment"],
            "safety": [
                "authorize_write_actions",
                "ensure_branch",
                "apply_patch_and_commit",
                "apply_text_update_and_commit",
                "update_files_and_open_pr",
            ],
            "execution": ["run_command", "run_tests"],
            "diffs": ["build_unified_diff", "build_section_based_diff"],
            "large_files": [
                "get_file_slice",
                "build_section_based_diff",
                "build_unified_diff_from_strings",
                "validate_json_string",
            ],
        },
        "guardrails": [
            "Always verify branch and ref inputs; missing refs for controller repos should fall back to the configured default branch.",
            "Do not bypass write gating by invoking GitHub APIs directly; use the provided tools so auditing stays consistent.",
            "When content drift is detected, refetch files and rebuild the change instead of retrying blindly.",
            "Prefer slice-and-diff workflows for large files and avoid echoing entire buffers unless necessary.",
            "Pause and summarize after repeated failures instead of looping on the same action; surface what has been checked so far.",
        ],
    }


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
        resp = await client.get(url)
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
    """Perform GitHub search queries (code, repos, issues, or commits)."""

    allowed_types = {"code", "repositories", "issues", "commits"}
    if search_type not in allowed_types:
        raise ValueError(f"type must be one of {sorted(allowed_types)}")

    params: Dict[str, Any] = {"q": query, "per_page": per_page, "page": page}
    if sort:
        params["sort"] = sort
    if order:
        params["order"] = order
    return await _github_request("GET", f"/search/{search_type}", params=params)


@mcp_tool(write_action=False)
async def download_user_content(content_url: str) -> Dict[str, Any]:
    """Download user-provided content (sandbox/local/http) with base64 encoding."""

    body_bytes = await _load_body_from_content_url(
        content_url, context="download_user_content"
    )
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

        tool_info: Dict[str, Any] = {
            "name": name_str,
            "description": description.strip(),
            "tags": sorted(list(getattr(tool, "tags", []) or [])),
            "write_action": bool(meta.get("write_action")),
            "auto_approved": bool(meta.get("auto_approved")),
            "read_only_hint": getattr(annotations, "readOnlyHint", None),
        }

        if include_parameters:
            input_schema = None
            schema = getattr(tool, "inputSchema", None)
            if schema is not None:
                try:
                    input_schema = schema.model_dump()
                except Exception:
                    input_schema = None
            else:
                try:
                    input_schema = getattr(tool, "parameters", None)
                except Exception:
                    input_schema = None

            tool_info["input_schema"] = input_schema

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
    """Fetch raw logs for a GitHub Actions job without truncation."""

    client = _github_client_instance()
    request = client.build_request(
        "GET",
        f"/repos/{full_name}/actions/jobs/{job_id}/logs",
        headers={"Accept": "application/vnd.github+json"},
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


@mcp_tool(write_action=True)
async def create_issue(
    full_name: str,
    title: str,
    body: Optional[str] = None,
    labels: Optional[List[str]] = None,
    assignees: Optional[List[str]] = None,
) -> Dict[str, Any]:
    # Create a GitHub issue with optional body, labels, and assignees.

    if '/' not in full_name:
        raise ValueError('full_name must be in owner/repo format')

    _ensure_write_allowed(f'create issue in {full_name}: {title!r}')

    payload: Dict[str, Any] = {'title': title}
    if body is not None:
        payload['body'] = body
    if labels is not None:
        payload['labels'] = labels
    if assignees is not None:
        payload['assignees'] = assignees

    return await _github_request(
        'POST',
        f'/repos/{full_name}/issues',
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

    if '/' not in full_name:
        raise ValueError('full_name must be in owner/repo format')

    _ensure_write_allowed(f'update issue #{issue_number} in {full_name}')

    payload: Dict[str, Any] = {}
    if title is not None:
        payload['title'] = title
    if body is not None:
        payload['body'] = body
    if state is not None:
        allowed_states = {'open', 'closed'}
        if state not in allowed_states:
            raise ValueError('state must be ‘open’ or ‘closed’')
        payload['state'] = state
    if labels is not None:
        payload['labels'] = labels
    if assignees is not None:
        payload['assignees'] = assignees

    if not payload:
        raise ValueError('At least one field must be provided to update_issue')

    return await _github_request(
        'PATCH',
        f'/repos/{full_name}/issues/{issue_number}',
        json_body=payload,
    )


@mcp_tool(write_action=True)
async def comment_on_issue(
    full_name: str,
    issue_number: int,
    body: str,
) -> Dict[str, Any]:
    # Post a comment on an issue.

    if '/' not in full_name:
        raise ValueError('full_name must be in owner/repo format')

    _ensure_write_allowed(f'comment on issue #{issue_number} in {full_name}')

    return await _github_request(
        'POST',
        f'/repos/{full_name}/issues/{issue_number}/comments',
        json_body={'body': body},
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
        raise GitHubAPIError(
            f"GitHub ensure_branch error {resp.status_code}: {resp.text}"
        )
    return {"status_code": resp.status_code, "json": resp.json()}
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
    _ensure_write_allowed(
        f"create PR from {head} to {base} in {full_name}"
    )
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
    """Commit multiple files, verify each, then open a PR in one call."""

    current_path: Optional[str] = None
    try:
        effective_base = _effective_ref_for_repo(full_name, base_branch)
        _ensure_write_allowed(f"update_files_and_open_pr {full_name} {title}")

        if not files:
            raise ValueError("files must contain at least one item")

        # 1) Ensure a dedicated branch exists
        branch = new_branch or f"ally-{os.urandom(4).hex()}"
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
                        context=(
                            f"update_files_and_open_pr({full_name}/{current_path})"
                        ),
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
                verification = await _verify_file_on_branch(
                    full_name, current_path, branch
                )
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
        return _structured_tool_error(
            exc, context="update_files_and_open_pr", path=current_path
        )

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

    This is a lower-level building block for "diff-first" flows:

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

    _ensure_write_allowed(f"apply_text_update_and_commit {full_name} {path}")

    effective_branch = _effective_ref_for_repo(full_name, branch)

    # 1) Read the current file state on the target branch, treating a 404 as a new file.
    is_new_file = False
    try:
        decoded = await _decode_github_content(full_name, path, effective_branch)
        old_text = decoded.get("text")
        if not isinstance(old_text, str):
            raise GitHubAPIError("Decoded content is not text")
        sha_before = decoded.get("sha")
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
    sha_after = verified.get("sha")

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
    branch: str = "main",
    message: Optional[str] = None,
    return_diff: bool = True,
) -> Dict[str, Any]:
    """Apply a unified diff to a single file, commit it, then verify it.

    This is a first-class patch-based flow for a single file:

      1. Read the current file text from GitHub on the given branch.
      2. Apply a unified diff (for that file) in memory.
      3. Commit the resulting text via the GitHub Contents API.
      4. Re-read the file on the branch to verify the new SHA and contents.

    The patch is expected to be a standard unified diff for *this* path,
    typically generated by `build_unified_diff` against the same branch.

    Args:
        full_name: "owner/repo" string.
        path: Path of the file within the repository.
        patch: Unified diff text affecting this path only.
        branch: Branch to commit to (default "main").
        message: Commit message; if omitted, "Update <path> via patch" is used.
        return_diff: If true, include a recomputed unified diff between the
            old and new text (not just echo the incoming patch).

    Returns:
        A dict with:
            - status: "committed"
            - full_name, path, branch
            - message: commit message used
            - commit: raw GitHub commit API response
            - verification: {sha_before, sha_after, html_url}
            - diff: unified diff text (if return_diff is true)
    """

    _ensure_write_allowed(f"apply_patch_and_commit {full_name} {path}")

    effective_branch = _effective_ref_for_repo(full_name, branch)

    import re
    import difflib

    def _apply_unified_diff_to_text(original_text: str, patch_text: str) -> str:
        """Apply a unified diff to original_text and return the updated text.

        This implementation supports patches for a single file with one or more
        hunks, of the form typically produced by difflib.unified_diff. It
        ignores "diff --git", "index", and file header lines, and processes
        only hunk headers and +/-/space lines.
        """
        orig_lines = original_text.splitlines(keepends=True)
        new_lines: list[str] = []

        orig_idx = 0
        in_hunk = False

        hunk_header_re = re.compile(
            r"^@@ -(?P<old_start>\d+)(?:,(?P<old_len>\d+))? "
            r"\+(?P<new_start>\d+)(?:,(?P<new_len>\d+))? @@"
        )

        for line in patch_text.splitlines(keepends=True):
            if line.startswith("diff --git") or line.startswith("index "):
                # Ignore Git metadata lines.
                continue
            if line.startswith("--- ") or line.startswith("+++ "):
                # Ignore file header lines; we assume the caller passes `path`.
                continue

            m = hunk_header_re.match(line)
            if m:
                # Start of a new hunk: flush unchanged lines up to old_start-1.
                old_start = int(m.group("old_start"))
                target_idx = old_start - 1 if old_start > 0 else 0

                if target_idx < orig_idx:
                    raise GitHubAPIError(
                        f"Patch is inconsistent with original text: "
                        f"target_idx={target_idx} < orig_idx={orig_idx}"
                    )

                new_lines.extend(orig_lines[orig_idx:target_idx])
                orig_idx = target_idx
                in_hunk = True
                continue

            if not in_hunk:
                # Skip any preamble before the first hunk.
                continue

            if line.startswith(" "):
                # Context line: must match original; copy from original.
                if orig_idx >= len(orig_lines):
                    raise GitHubAPIError("Patch context extends beyond end of file")
                # Optionally, we could assert that orig_lines[orig_idx] == line[1:].
                new_lines.append(orig_lines[orig_idx])
                orig_idx += 1
            elif line.startswith("-"):
                # Deletion line: skip the corresponding original line.
                if orig_idx >= len(orig_lines):
                    raise GitHubAPIError("Patch deletion extends beyond end of file")
                # We could assert orig_lines[orig_idx] == line[1:].
                orig_idx += 1
            elif line.startswith("+"):
                # Insertion line: add the new text (without the leading '+').
                new_lines.append(line[1:])
            elif line.startswith("\\"):
                # e.g. "\ No newline at end of file" – ignore.
                continue
            else:
                raise GitHubAPIError(f"Unexpected line in patch: {line!r}")

        # Append any remaining original lines not touched by hunks.
        new_lines.extend(orig_lines[orig_idx:])
        return "".join(new_lines)

    # 1) Read current file from GitHub on the target branch. Treat a 404 as a new file.
    is_new_file = False
    try:
        decoded = await _decode_github_content(full_name, path, effective_branch)
        old_text = decoded.get("text")
        if not isinstance(old_text, str):
            raise GitHubAPIError("Decoded content is not text")
        sha_before = decoded.get("sha")
    except GitHubAPIError as exc:
        msg = str(exc)
        if "404" in msg and "/contents/" in msg:
            is_new_file = True
            old_text = ""
            sha_before = None
        else:
            raise

    # 2) Apply the patch to get the updated text.
    try:
        new_text = _apply_unified_diff_to_text(old_text, patch)
    except Exception as exc:
        raise GitHubAPIError(f"Failed to apply patch to {path}: {exc}") from exc

    body_bytes = new_text.encode("utf-8")
    default_message = "Create" if is_new_file else "Update"
    commit_message = message or f"{default_message} {path} via patch"

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
    new_text_verified = verified.get("text")
    sha_after = verified.get("sha")

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

    # Optional: recompute a unified diff between old and verified new text.
    if return_diff:
        diff_iter = difflib.unified_diff(
            old_text.splitlines(keepends=True),
            (new_text_verified or "").splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
        result["diff"] = "".join(diff_iter)

    return result


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
    use_temp_venv: bool = True,
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
        use_temp_venv: When true (default), commands run inside a temporary
            virtualenv rooted in the workspace so ``pip install`` steps do not
            mutate the server-wide environment.

    The temporary directory is cleaned up automatically after execution, so
    callers should capture any artifacts they need from ``result.stdout`` or by
    writing to remote destinations during the command itself.
    """

    repo_dir: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    try:
        effective_ref = _effective_ref_for_repo(full_name, ref)
        _ensure_write_allowed(
            f"run_command {command} in {full_name}@{effective_ref}"
        )
        repo_dir = await _clone_repo(full_name, ref=effective_ref)

        if patch:
            await _apply_patch_to_repo(repo_dir, patch)

        if use_temp_venv:
            env = await _prepare_temp_virtualenv(repo_dir)

        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)
        result = await _run_shell(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )
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
    use_temp_venv: bool = True,
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
        use_temp_venv=use_temp_venv,
    )


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


def _build_health_payload() -> Dict[str, Any]:
    """Construct a small JSON health payload for the HTTP endpoint.

    This keeps the HTTP health check aligned with the controller configuration
    and exposes a minimal view of in-process metrics without changing any of the
    structured log shapes validated elsewhere.
    """

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
    """Lightweight JSON health endpoint with metrics summary.

    The body is intentionally small: a status flag, uptime, basic controller
    configuration, and a compact metrics snapshot suitable for logs or external
    polling.
    """

    payload = _build_health_payload()
    return JSONResponse(payload)

async def _shutdown_clients() -> None:
    if _http_client_github is not None:
        await _http_client_github.aclose()
    if _http_client_external is not None:
        await _http_client_external.aclose()


app.add_event_handler("shutdown", _shutdown_clients)
