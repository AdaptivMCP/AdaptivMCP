"""
GitHub Fast MCP server exposing common read/write utilities for private repositories.

This server is designed to run both locally and on platforms like Render. It
exposes a FastMCP-based toolset over Server-Sent Events (SSE) at `/sse`, plus
a small HTTP surface (`/` and `/healthz`) for health checks.

Key capabilities:
- Read GitHub repo metadata, branches, files (single or batched), rate limits.
- Inspect GitHub Actions runs, jobs, and logs.
- Write operations (opt-in): create branches, commit files, open pull requests.
- Higher-level workflows: ensure branches, update multiple files, open PRs.
- Large-file support for private repos via `commit_file(..., content_url=...)`.

Environment variables:
- GITHUB_PAT or GITHUB_TOKEN (required)
- GITHUB_API_BASE, GITHUB_GRAPHQL_URL (optional)
- GITHUB_MCP_AUTO_APPROVE (optional)
- HTTPX_* tuning vars (optional)
- FETCH_FILES_CONCURRENCY / MAX_CONCURRENCY (optional)
"""
from __future__ import annotations

import asyncio
import base64
import os
import secrets
from functools import wraps
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise RuntimeError(
        "GITHUB_PAT or GITHUB_TOKEN environment variable must be set for private repo access."
    )

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_GRAPHQL_URL = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")

# HTTP tuning; fall back to HTTP_TIMEOUT_SECONDS if HTTPX_TIMEOUT not set
HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", os.environ.get("HTTP_TIMEOUT_SECONDS", "120")))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "100"))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "200"))
HTTPX_HTTP2 = os.environ.get("HTTPX_HTTP2", "0") != "0"

# Concurrency limit for fetch_files; respect either FETCH_FILES_CONCURRENCY or MAX_CONCURRENCY
FETCH_FILES_CONCURRENCY = int(
    os.environ.get("FETCH_FILES_CONCURRENCY", os.environ.get("MAX_CONCURRENCY", "256"))
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class GitHubAuthError(RuntimeError):
    """Raised when a write action is attempted without prior approval."""


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns a non-success status code."""


# ---------------------------------------------------------------------------
# MCP setup and decorator compatibility
# ---------------------------------------------------------------------------
mcp = FastMCP("GitHub Fast MCP", json_response=True)
WRITE_ACTIONS_APPROVED: bool = os.environ.get("GITHUB_MCP_AUTO_APPROVE", "0") != "0"


def mcp_tool(*, write_action: bool = False, **kwargs):
    """
    Compatibility wrapper for @mcp.tool that preserves the write_action metadata.

    Older FastMCP versions may reject unknown kwargs, so we try to pass
    write_action through and fall back to a simpler registration if necessary.
    """

    def decorator(func):
        try:
            tool = mcp.tool(write_action=write_action, **kwargs)(func)
        except TypeError:
            tool = mcp.tool(**kwargs)(func)

        @wraps(func)
        async def wrapper(*args, **inner_kwargs):
            return await tool(*args, **inner_kwargs)

        # Attach metadata so MCP clients can see read/write intent.
        for obj in (func, tool, wrapper):
            try:
                setattr(obj, "write_action", write_action)
                obj.__dict__["write_action"] = write_action
            except Exception:
                pass

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# HTTPX clients
# ---------------------------------------------------------------------------
_github_client: Optional[httpx.AsyncClient] = None
_external_client: Optional[httpx.AsyncClient] = None


def _github_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "GitHub-Fast-MCP/1.0",
        "Connection": "keep-alive",
    }


def _build_client(base_url: Optional[str] = None) -> httpx.AsyncClient:
    limits = httpx.Limits(
        max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
        max_connections=HTTPX_MAX_CONNECTIONS,
    )
    headers = _github_headers() if base_url else {"User-Agent": "GitHub-Fast-MCP/1.0"}
    try:
        return httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(HTTPX_TIMEOUT),
            limits=limits,
            follow_redirects=True,
            http2=HTTPX_HTTP2,
            headers=headers,
            trust_env=False,
        )
    except RuntimeError as exc:
        # Some environments disallow HTTP/2; fall back to HTTP/1.1
        if "http2" in str(exc).lower():
            return httpx.AsyncClient(
                base_url=base_url,
                timeout=httpx.Timeout(HTTPX_TIMEOUT),
                limits=limits,
                follow_redirects=True,
                http2=False,
                headers=headers,
                trust_env=False,
            )
        raise


def _github_client_instance() -> httpx.AsyncClient:
    global _github_client
    if _github_client is None:
        _github_client = _build_client(GITHUB_API_BASE)
    return _github_client


def _external_client_instance() -> httpx.AsyncClient:
    global _external_client
    if _external_client is None:
        _external_client = _build_client()
    return _external_client


async def _close_clients() -> None:
    global _github_client, _external_client
    if _github_client is not None:
        await _github_client.aclose()
        _github_client = None
    if _external_client is not None:
        await _external_client.aclose()
        _external_client = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _ensure_write_allowed(action: str) -> None:
    if not WRITE_ACTIONS_APPROVED:
        raise GitHubAuthError(
            "Write operations require prior approval. "
            "Call authorize_write_actions before attempting to "
            f"{action}."
        )


async def _github_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
) -> Dict[str, Any]:
    client = _github_client_instance()
    response = await client.request(method.upper(), path, params=params, json=json_body)
    result: Dict[str, Any] = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
    }
    try:
        result["json"] = response.json()
    except Exception:
        result["text"] = response.text
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub API error {response.status_code}: {response.text}")
    return result


def _decode_github_content(data: Dict[str, Any]) -> Dict[str, Any]:
    decoded: Optional[str] = None
    if isinstance(data, dict) and data.get("encoding") == "base64" and "content" in data:
        decoded = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return {"decoded": decoded, "raw": data}


async def _github_graphql(
    query: str, variables: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    client = _github_client_instance()
    response = await client.post(
        GITHUB_GRAPHQL_URL, json={"query": query, "variables": variables or {}}
    )
    result: Dict[str, Any] = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
    }
    try:
        result["json"] = response.json()
    except Exception:
        result["text"] = response.text
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub GraphQL error {response.status_code}: {response.text}")
    return result


async def _ensure_branch_internal(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """
    Ensure a branch exists. If it does not, create it from from_ref.

    Returns:
        {
          "created": bool,
          "ref": <raw ref JSON from GitHub (if available)>
        }
    """
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    client = _github_client_instance()
    # Check if the branch already exists
    resp = await client.get(
        f"/repos/{full_name.strip()}/git/refs/heads/{branch}"
    )
    if resp.status_code == 200:
        return {"created": False, "ref": resp.json()}

    if resp.status_code != 404:
        raise GitHubAPIError(
            f"Error looking up branch {branch}: {resp.status_code} {resp.text}"
        )

    # Need to create it from from_ref
    ref_info = await _github_request(
        "GET",
        f"/repos/{full_name.strip()}/git/refs/heads/{from_ref}",
    )
    sha = ref_info.get("json", {}).get("object", {}).get("sha")
    if not sha:
        raise GitHubAPIError("Unable to resolve source ref SHA for branch creation")

    payload = {"ref": f"refs/heads/{branch}", "sha": sha}
    created = await _github_request(
        "POST",
        f"/repos/{full_name.strip()}/git/refs",
        json_body=payload,
    )
    return {"created": True, "ref": created.get("json", {})}


# ---------------------------------------------------------------------------
# Tools (read)
# ---------------------------------------------------------------------------
@mcp_tool(write_action=False)
async def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    """Enable or disable write tools (branch/commit/PR) for this MCP session."""
    global WRITE_ACTIONS_APPROVED
    WRITE_ACTIONS_APPROVED = bool(approved)
    return {"write_actions_enabled": WRITE_ACTIONS_APPROVED}


@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    """Show current GitHub REST API rate limits for the configured token."""
    return await _github_request("GET", "/rate_limit")


@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> Dict[str, Any]:
    """Return repository metadata (owner/repo, default branch, visibility, etc.)."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    return await _github_request("GET", f"/repos/{full_name.strip()}")


@mcp_tool(write_action=False)
async def list_branches(
    full_name: str,
    per_page: int = 100,
    page: int = 1,
) -> Dict[str, Any]:
    """List branches for a repository (paginated)."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    params = {"per_page": per_page, "page": page}
    return await _github_request("GET", f"/repos/{full_name.strip()}/branches", params=params)


@mcp_tool(write_action=False)
async def get_file_contents(
    full_name: str,
    path: str,
    ref: str = "main",
) -> Dict[str, Any]:
    """Fetch a single file’s contents plus raw GitHub metadata (content/encoding/etc.)."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    result = await _github_request(
        "GET",
        f"/repos/{full_name.strip()}/contents/{path.lstrip('/')}",
        params={"ref": ref},
    )
    data = result.get("json", {})
    decoded = _decode_github_content(data)
    return {"status": result["status"], "path": path, "ref": ref, **decoded}


@mcp_tool(write_action=False)
async def fetch_files(
    full_name: str,
    paths: list[str],
    ref: str = "main",
) -> Dict[str, Any]:
    """Fetch multiple files concurrently; each result includes decoded text and raw metadata."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if not paths:
        raise ValueError("paths must include at least one entry")

    semaphore = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def _fetch(single_path: str) -> Dict[str, Any]:
        async with semaphore:
            try:
                result = await _github_request(
                    "GET",
                    f"/repos/{full_name.strip()}/contents/{single_path.lstrip('/')}",
                    params={"ref": ref},
                )
                data = result.get("json", {})
                decoded = _decode_github_content(data)
                return {
                    "path": single_path,
                    "status": result["status"],
                    "ref": ref,
                    **decoded,
                }
            except Exception as exc:
                return {"path": single_path, "error": str(exc)}

    results = await asyncio.gather(*[_fetch(p) for p in paths])
    return {"count": len(results), "results": results}


@mcp_tool(write_action=False)
async def graphql_query(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run an arbitrary GraphQL query against the GitHub GraphQL API."""
    return await _github_graphql(query, variables)


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch an external URL for diagnostics or simple checks (not GitHub-specific)."""
    client = _external_client_instance()
    response = await client.get(url)
    return {
        "status": response.status_code,
        "url": str(response.url),
        "text": response.text,
    }


@mcp_tool(write_action=False)
async def list_workflow_runs(
    full_name: str,
    *,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    event: Optional[str] = None,
    per_page: int = 20,
    page: int = 1,
) -> Dict[str, Any]:
    """List recent GitHub Actions workflow runs with optional branch/status/event filters."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    if event:
        params["event"] = event

    return await _github_request(
        "GET",
        f"/repos/{full_name.strip()}/actions/runs",
        params=params,
    )


@mcp_tool(write_action=False)
async def get_workflow_run(
    full_name: str,
    run_id: int,
) -> Dict[str, Any]:
    """Get details for a specific GitHub Actions workflow run."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    return await _github_request(
        "GET",
        f"/repos/{full_name.strip()}/actions/runs/{run_id}",
    )


@mcp_tool(write_action=False)
async def list_workflow_run_jobs(
    full_name: str,
    run_id: int,
    per_page: int = 50,
    page: int = 1,
) -> Dict[str, Any]:
    """List jobs (and their statuses) for a given GitHub Actions workflow run."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name.strip()}/actions/runs/{run_id}/jobs",
        params=params,
    )


@mcp_tool(write_action=False)
async def get_job_logs(
    full_name: str,
    job_id: int,
) -> Dict[str, Any]:
    """Fetch raw logs for a GitHub Actions job (useful for debugging failed workflows)."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    client = _github_client_instance()
    response = await client.get(
        f"/repos/{full_name.strip()}/actions/jobs/{job_id}/logs"
    )
    result: Dict[str, Any] = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
    }
    try:
        result["text"] = response.text
    except Exception:
        result["content"] = base64.b64encode(response.content).decode("utf-8")

    if response.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {response.status_code}: {result.get('text', '')}"
        )
    return result


@mcp_tool(write_action=False)
async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """
    Poll a workflow run until it completes or times out.

    Returns a summary including final status, conclusion, timed_out flag,
    and the last run JSON payload.
    """
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if poll_interval_seconds <= 0:
        raise ValueError("poll_interval_seconds must be positive")

    elapsed = 0
    last_run: Optional[Dict[str, Any]] = None
    polls = 0

    while elapsed < timeout_seconds:
        run_info = await get_workflow_run(full_name, run_id)
        run_json = run_info.get("json") or run_info.get("json", {})
        last_run = run_json
        polls += 1

        status = run_json.get("status")
        conclusion = run_json.get("conclusion")
        if status == "completed":
            return {
                "timed_out": False,
                "polls": polls,
                "status": status,
                "conclusion": conclusion,
                "run": run_json,
            }

        await asyncio.sleep(poll_interval_seconds)
        elapsed += poll_interval_seconds

    return {
        "timed_out": True,
        "polls": polls,
        "status": last_run.get("status") if last_run else None,
        "conclusion": last_run.get("conclusion") if last_run else None,
        "run": last_run,
    }


# ---------------------------------------------------------------------------
# Tools (write)
# ---------------------------------------------------------------------------
@mcp_tool(write_action=True)
async def create_branch(
    full_name: str,
    new_branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """Create a new branch at the tip of an existing ref (requires write actions enabled)."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    await _ensure_write_allowed(f"create branch {new_branch}")

    ref_info = await _github_request(
        "GET",
        f"/repos/{full_name.strip()}/git/refs/heads/{from_ref}",
    )
    sha = ref_info.get("json", {}).get("object", {}).get("sha")
    if not sha:
        raise GitHubAPIError("Unable to resolve source ref SHA")

    payload = {"ref": f"refs/heads/{new_branch}", "sha": sha}
    return await _github_request(
        "POST",
        f"/repos/{full_name.strip()}/git/refs",
        json_body=payload,
    )


@mcp_tool(write_action=True)
async def ensure_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    """
    Ensure a branch exists (idempotent).

    If the branch exists, returns its ref info with created=False.
    If missing, creates it from from_ref and returns created=True.
    """
    await _ensure_write_allowed(f"ensure branch {branch}")
    return await _ensure_branch_internal(full_name, branch, from_ref)


@mcp_tool(write_action=True)
async def commit_file(
    full_name: str,
    path: str,
    message: str,
    content: Optional[str] = None,
    *,
    content_url: Optional[str] = None,
    branch: str = "main",
    sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a file in a repo (write tool).

    Use ``content`` for normal-sized text files.

    Use ``content_url`` for large or uploaded files (for example,
    sandbox paths in ChatGPT); the server fetches the bytes and
    commits them to the target private repo.
    """
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    await _ensure_write_allowed(f"commit file {path}")

    if content is None and content_url is None:
        raise ValueError("Either content or content_url must be provided")
    if content is not None and content_url is not None:
        raise ValueError("Provide content or content_url, but not both")

    body_bytes: Optional[bytes] = None

    if content_url is not None:
        parsed = urlparse(content_url)

        if parsed.scheme in ("http", "https"):
            # ChatGPT / platform will transform sandbox paths into HTTP URLs.
            client = _external_client_instance()
            response = await client.get(content_url)
            if response.status_code >= 400:
                raise GitHubAPIError(
                    f"Failed to fetch content from {content_url}: "
                    f"{response.status_code}"
                )
            body_bytes = response.content
        else:
            # Treat as local filesystem path (including file:// URIs)
            file_path = parsed.path if parsed.scheme == "file" else content_url
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"Content path not found: {file_path}")
            with open(file_path, "rb") as fp:
                body_bytes = fp.read()
    else:
        # Inline content is treated as UTF-8 text
        body_bytes = content.encode("utf-8")

    assert body_bytes is not None

    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(body_bytes).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha

    return await _github_request(
        "PUT",
        f"/repos/{full_name.strip()}/contents/{path.lstrip('/')}",
        json_body=payload,
    )


@mcp_tool(write_action=True)
async def create_pull_request(
    full_name: str,
    title: str,
    head: str,
    base: str = "main",
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """Open a pull request from head to base (requires write actions enabled)."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    await _ensure_write_allowed(f"open PR from {head} to {base}")

    payload: Dict[str, Any] = {
        "title": title,
        "head": head,
        "base": base,
        "draft": draft,
    }
    if body:
        payload["body"] = body

    return await _github_request(
        "POST",
        f"/repos/{full_name.strip()}/pulls",
        json_body=payload,
    )


@mcp_tool(write_action=True)
async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Trigger a workflow_dispatch workflow.

    `workflow` may be a numeric ID or a workflow file name (e.g. 'ci.yml').
    """
    await _ensure_write_allowed(f"trigger workflow_dispatch on {workflow}")

    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    payload: Dict[str, Any] = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs

    return await _github_request(
        "POST",
        f"/repos/{full_name.strip()}/actions/workflows/{workflow}/dispatches",
        json_body=payload,
    )


@mcp_tool(write_action=True)
async def update_files_and_open_pr(
    full_name: str,
    title: str,
    files: list[Dict[str, Any]],
    *,
    base_branch: str = "main",
    new_branch: Optional[str] = None,
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """
    High-level workflow: ensure branch, commit multiple files, open a PR.

    Args:
        full_name: 'owner/repo'.
        title: PR title.
        files: list of dicts, each with:
            - 'path' (required)
            - 'content' or 'content_url' (one required)
            - optional 'message' (per-file commit message; defaults to generic).
        base_branch: branch to base from (default 'main').
        new_branch: branch to use; if None, an 'ally-<base>-auto-xxxx' name is generated.
        body: PR body (optional).
        draft: whether to create the PR as a draft.
    """
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    if not files:
        raise ValueError("files must contain at least one entry")

    await _ensure_write_allowed("update files and open PR")

    branch = new_branch or f"ally-{base_branch}-auto-{secrets.token_hex(4)}"

    # Ensure the working branch exists
    branch_info = await _ensure_branch_internal(full_name, branch, from_ref=base_branch)

    # For each file, determine if it already exists on the branch and capture sha if so.
    client = _github_client_instance()
    commit_results: list[Dict[str, Any]] = []

    for f in files:
        path = f.get("path")
        if not path:
            raise ValueError("Each file entry must include 'path'")

        content = f.get("content")
        content_url = f.get("content_url")
        message = f.get("message") or f"Update {path} via update_files_and_open_pr"

        if content is None and content_url is None:
            raise ValueError(f"File {path}: either 'content' or 'content_url' must be provided")
        if content is not None and content_url is not None:
            raise ValueError(f"File {path}: provide only one of 'content' or 'content_url'")

        sha: Optional[str] = None
        resp = await client.get(
            f"/repos/{full_name.strip()}/contents/{path.lstrip('/')}",
            params={"ref": branch},
        )
        if resp.status_code == 200:
            data = resp.json()
            sha = data.get("sha")
        elif resp.status_code not in (200, 404):
            raise GitHubAPIError(
                f"Error checking existing file {path}: {resp.status_code} {resp.text}"
            )

        commit_result = await commit_file(
            full_name=full_name,
            path=path,
            message=message,
            content=content,
            content_url=content_url,
            branch=branch,
            sha=sha,
        )
        commit_results.append({"path": path, "result": commit_result})

    # Open the PR
    pr_body = body or f"Automated changes via update_files_and_open_pr on branch `{branch}`."
    pr_result = await create_pull_request(
        full_name=full_name,
        title=title,
        head=branch,
        base=base_branch,
        body=pr_body,
        draft=draft,
    )

    return {
        "branch": branch,
        "branch_created": branch_info.get("created", False),
        "commits": commit_results,
        "pull_request": pr_result,
    }


# ---------------------------------------------------------------------------
# ASGI wiring (FastMCP SSE app + Starlette)
# ---------------------------------------------------------------------------
_sse_app = mcp.sse_app()


async def _sse_endpoint(scope, receive, send):
    """
    ASGI wrapper for the MCP SSE app.

    - Accepts GET/POST/HEAD/OPTIONS for compatibility with MCP clients.
    - Normalizes scope so FastMCP always sees absolute paths like `/sse`.
    - For non-HTTP scopes, forwards directly to the FastMCP app.
    """
    if scope.get("type") != "http":
        return await _sse_app(scope, receive, send)

    path = scope.get("path", "") or "/"
    method = scope.get("method", "GET").upper()

    if method == "OPTIONS":
        response = PlainTextResponse("OK", status_code=204)
        await response(scope, receive, send)
        return

    if method not in {"GET", "POST", "HEAD", "OPTIONS"}:
        response = PlainTextResponse("Method Not Allowed", status_code=405)
        await response(scope, receive, send)
        return

    normalized_scope = dict(scope)
    normalized_scope["root_path"] = ""
    if not normalized_scope.get("path", "").startswith("/"):
        normalized_scope["path"] = "/" + normalized_scope.get("path", "")

    return await _sse_app(normalized_scope, receive, send)


routes = [
    Route(
        "/",
        lambda request: PlainTextResponse(
            "GitHub Fast MCP server active. Connect to /sse for the event stream.",
            status_code=200,
        ),
        methods=["GET", "HEAD"],
    ),
    Route(
        "/healthz",
        lambda request: PlainTextResponse("ok", status_code=200),
        methods=["GET", "HEAD"],
        name="healthz",
    ),
    # All remaining paths (including /sse and /messages) go through the MCP SSE app.
    Mount("/", app=_sse_endpoint),
]

app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.router.redirect_slashes = False
app.add_event_handler(
    "shutdown",
    lambda: asyncio.create_task(_close_clients()),
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
