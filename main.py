import os
import asyncio
import base64
import tempfile
import shutil
import time
import secrets
import uuid
import json
import textwrap
import urllib.parse
from typing import Optional, Dict, Any, List

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route, Mount
from starlette.middleware.cors import CORSMiddleware
from fastmcp import FastMCP, Context
from mcp.types import TextContent
import uvicorn

# --------------------------------------------------------------------
# Configuration and constants
# --------------------------------------------------------------------

GITHUB_API_BASE = "https://api.github.com"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

HTTPX_HTTP2 = bool(int(os.environ.get("HTTPX_HTTP2", "1")))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "300"))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "200"))
HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", "150"))

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "80"))
FETCH_FILES_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", str(MAX_CONCURRENCY)))

TOOL_STDOUT_MAX_CHARS = int(os.environ.get("TOOL_STDOUT_MAX_CHARS", "12000"))
TOOL_STDERR_MAX_CHARS = int(os.environ.get("TOOL_STDERR_MAX_CHARS", "12000"))

# --------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------


class GitHubAuthError(RuntimeError):
    pass


class GitHubAPIError(RuntimeError):
    pass


# --------------------------------------------------------------------
# MCP server
# --------------------------------------------------------------------

mcp = FastMCP("GitHub Fast MCP", json_response=True)
WRITE_ALLOWED = False


def mcp_tool(*tool_args, write_action: bool = False, **tool_kwargs):
    """
    Decorator that wraps mcp.tool and attaches write_action metadata
    so clients can distinguish read vs write tools.
    """
    def decorator(func):
        # Attach metadata on the underlying function object (not the FastMCP tool wrapper)
        # to avoid mutating the Pydantic model returned by mcp.tool().
        setattr(func, "write_action", write_action)
        return mcp.tool(*tool_args, **tool_kwargs)(func)
    return decorator


@mcp_tool(write_action=False)
async def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    global WRITE_ALLOWED
    WRITE_ALLOWED = bool(approved)
    return {"write_actions_enabled": WRITE_ALLOWED}


def _ensure_write_allowed(context: str):
    if not WRITE_ALLOWED:
        raise GitHubAPIError(f"Write tools are not authorized for this session (context: {context})")


# --------------------------------------------------------------------
# GitHub helpers
# --------------------------------------------------------------------

_github_client: Optional[httpx.AsyncClient] = None
_external_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


def _github_headers() -> Dict[str, str]:
    token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN must be set")
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-mcp-server",
    }


async def _github_client_instance() -> httpx.AsyncClient:
    global _github_client
    async with _client_lock:
        if _github_client is None:
            _github_client = httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                headers=_github_headers(),
                timeout=HTTPX_TIMEOUT,
                http2=HTTPX_HTTP2,
                limits=httpx.Limits(
                    max_connections=HTTPX_MAX_CONNECTIONS,
                    max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
                ),
            )
        return _github_client


async def _external_client_instance() -> httpx.AsyncClient:
    global _external_client
    async with _client_lock:
        if _external_client is None:
            _external_client = httpx.AsyncClient(
                timeout=HTTPX_TIMEOUT,
                http2=HTTPX_HTTP2,
                limits=httpx.Limits(
                    max_connections=HTTPX_MAX_CONNECTIONS,
                    max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
                ),
            )
        return _external_client


async def _close_clients():
    global _github_client, _external_client
    if _github_client is not None:
        await _github_client.aclose()
        _github_client = None
    if _external_client is not None:
        await _external_client.aclose()
        _external_client = None


async def _github_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> httpx.Response:
    client = await _github_client_instance()
    resp = await client.request(method, path, params=params, json=json_body)
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = None
        message = data.get("message") if isinstance(data, dict) else None
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for {method} {path}: {message or resp.text}"
        )
    return resp


async def _github_graphql(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = await _github_client_instance()
    payload = {"query": query, "variables": variables or {}}
    resp = await client.post(GITHUB_GRAPHQL_URL, json=payload)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub GraphQL error {resp.status_code}: {resp.text}")
    data = resp.json()
    if "errors" in data:
        raise GitHubAPIError(f"GitHub GraphQL errors: {data['errors']}")
    return data["data"]


# --------------------------------------------------------------------
# Content decoding
# --------------------------------------------------------------------

async def _decode_github_content(full_name: str, path: str, ref: str = "main") -> Dict[str, Any]:
    resp = await _github_request(
        "GET",
        f"/repos/{full_name}/contents/{path}",
        params={"ref": ref},
    )
    data = resp.json()
    if isinstance(data, list):
        raise GitHubAPIError(f"Path {path} in {full_name}@{ref} is a directory, not a file")
    encoding = data.get("encoding")
    if encoding != "base64":
        raise GitHubAPIError(f"Unexpected encoding {encoding} for file {path}")
    content_b64 = data.get("content", "")
    # GitHub may include newlines in base64
    content_bytes = base64.b64decode(content_b64.encode("ascii"), validate=False)
    text = content_bytes.decode("utf-8", errors="replace")
    sha = data.get("sha")
    html_url = data.get("html_url")
    return {
        "status": "ok",
        "text": text,
        "sha": sha,
        "path": path,
        "html_url": html_url,
        "ref": ref,
    }


# --------------------------------------------------------------------
# Workspace helpers (clone, shell)
# --------------------------------------------------------------------

async def _run_shell(
    cmd: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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

    stdout_text = stdout_bytes.decode("utf-8", errors="replace")
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")

    if len(stdout_text) > TOOL_STDOUT_MAX_CHARS:
        stdout_text = stdout_text[:TOOL_STDOUT_MAX_CHARS] + "\n...[truncated]"
    if len(stderr_text) > TOOL_STDERR_MAX_CHARS:
        stderr_text = stderr_text[:TOOL_STDERR_MAX_CHARS] + "\n...[truncated]"

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }


async def _clone_repo(full_name: str, ref: str = "main") -> str:
    token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN must be set for git clone")

    tmpdir = tempfile.mkdtemp(prefix="github-mcp-")
    repo_url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    cmd = f"git clone --depth 1 --branch {ref} {repo_url} {tmpdir}"
    result = await _run_shell(cmd, timeout_seconds=600)
    if result["exit_code"] != 0:
        await _cleanup_dir(tmpdir)
        raise GitHubAPIError(f"Failed to clone repo: {result}")
    return tmpdir


async def _cleanup_dir(path: str):
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)


# --------------------------------------------------------------------
# Tools: control
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    resp = await _github_request("GET", "/rate_limit")
    return resp.json()


# --------------------------------------------------------------------
# Tools: repository inspection / reads
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> Dict[str, Any]:
    resp = await _github_request("GET", f"/repos/{full_name}")
    data = resp.json()
    keys = [
        "id",
        "name",
        "full_name",
        "private",
        "default_branch",
        "html_url",
        "description",
        "fork",
        "language",
        "archived",
        "disabled",
        "pushed_at",
        "created_at",
        "updated_at",
        "size",
    ]
    return {k: data.get(k) for k in keys}


@mcp_tool(write_action=False)
async def list_branches(
    full_name: str,
    per_page: int = 100,
    page: int = 1,
) -> Dict[str, Any]:
    resp = await _github_request(
        "GET", f"/repos/{full_name}/branches", params={"per_page": per_page, "page": page}
    )
    branches = resp.json()
    return {
        "branches": [
            {
                "name": b.get("name"),
                "protected": b.get("protected"),
                "sha": (b.get("commit") or {}).get("sha"),
            }
            for b in branches
        ]
    }


@mcp_tool(write_action=False)
async def get_file_contents(
    full_name: str,
    path: str,
    ref: str = "main",
) -> Dict[str, Any]:
    return await _decode_github_content(full_name, path, ref=ref)


@mcp_tool(write_action=False)
async def fetch_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
) -> Dict[str, Any]:
    """
    Fetch multiple files concurrently from a repo, trimming content to keep responses small.
    """
    results: Dict[str, Any] = {}
    sem = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def worker(p: str):
        async with sem:
            try:
                decoded = await _decode_github_content(full_name, p, ref=ref)
                text = decoded["text"]
                if len(text) > TOOL_STDOUT_MAX_CHARS:
                    text = text[:TOOL_STDOUT_MAX_CHARS] + "\n...[truncated]"
                results[p] = {
                    "status": "ok",
                    "text": text,
                    "sha": decoded.get("sha"),
                    "html_url": decoded.get("html_url"),
                }
            except Exception as exc:
                results[p] = {"status": "error", "error": str(exc)}

    await asyncio.gather(*(worker(p) for p in paths))
    return {"ref": ref, "files": results}


@mcp_tool(write_action=False)
async def graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = await _github_graphql(query, variables or {})
    # Trim large responses defensively
    as_text = json.dumps(data)
    if len(as_text) > TOOL_STDOUT_MAX_CHARS:
        as_text = as_text[:TOOL_STDOUT_MAX_CHARS] + "\n...[truncated]"
    return {"data": data, "raw": as_text}


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    """
    Fetch arbitrary URL content, used for sandbox file URLs or simple HTTP GETs.
    """
    client = await _external_client_instance()
    resp = await client.get(url)
    text = resp.text
    if len(text) > TOOL_STDOUT_MAX_CHARS:
        text = text[:TOOL_STDOUT_MAX_CHARS] + "\n...[truncated]"
    return {"status_code": resp.status_code, "text": text, "url": str(resp.url)}


# --------------------------------------------------------------------
# Tools: GitHub Actions
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def list_workflow_runs(
    full_name: str,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    event: Optional[str] = None,
    per_page: int = 20,
    page: int = 1,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    if event:
        params["event"] = event

    resp = await _github_request("GET", f"/repos/{full_name}/actions/runs", params=params)
    data = resp.json()
    runs = data.get("workflow_runs", [])
    trimmed_runs = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "head_branch": r.get("head_branch"),
            "status": r.get("status"),
            "conclusion": r.get("conclusion"),
            "event": r.get("event"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "html_url": r.get("html_url"),
        }
        for r in runs
    ]
    return {"total_count": data.get("total_count"), "workflow_runs": trimmed_runs}


@mcp_tool(write_action=False)
async def get_workflow_run(full_name: str, run_id: int) -> Dict[str, Any]:
    resp = await _github_request("GET", f"/repos/{full_name}/actions/runs/{run_id}")
    data = resp.json()
    keys = [
        "id",
        "name",
        "head_branch",
        "head_sha",
        "status",
        "conclusion",
        "event",
        "created_at",
        "updated_at",
        "run_number",
        "run_attempt",
        "html_url",
    ]
    return {k: data.get(k) for k in keys}


@mcp_tool(write_action=False)
async def list_workflow_run_jobs(
    full_name: str,
    run_id: int,
    per_page: int = 50,
    page: int = 1,
) -> Dict[str, Any]:
    resp = await _github_request(
        "GET",
        f"/repos/{full_name}/actions/runs/{run_id}/jobs",
        params={"per_page": per_page, "page": page},
    )
    data = resp.json()
    jobs = data.get("jobs", [])
    trimmed_jobs = [
        {
            "id": j.get("id"),
            "run_id": j.get("run_id"),
            "name": j.get("name"),
            "status": j.get("status"),
            "conclusion": j.get("conclusion"),
            "started_at": j.get("started_at"),
            "completed_at": j.get("completed_at"),
            "html_url": j.get("html_url"),
        }
        for j in jobs
    ]
    return {"total_count": data.get("total_count"), "jobs": trimmed_jobs}


@mcp_tool(write_action=False)
async def get_job_logs(full_name: str, job_id: int) -> Dict[str, Any]:
    # GitHub returns a redirect to the log artifact; httpx will follow
    resp = await _github_request("GET", f"/repos/{full_name}/actions/jobs/{job_id}/logs")
    content = resp.text
    if len(content) > 16000:
        content = content[:16000] + "\n...[truncated]"
    return {"job_id": job_id, "logs": content}


@mcp_tool(write_action=False)
async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """
    Poll a workflow run until completion or timeout.
    """
    start = time.time()
    last_state: Optional[Dict[str, Any]] = None

    while True:
        state = await get_workflow_run(full_name, run_id)
        last_state = state
        status = state.get("status")
        conclusion = state.get("conclusion")

        if status in {"completed", "failure", "cancelled"} or conclusion is not None:
            break

        if time.time() - start > timeout_seconds:
            return {"timed_out": True, "run": state}

        await asyncio.sleep(poll_interval_seconds)

    return {"timed_out": False, "run": last_state}


@mcp_tool(write_action=True)
async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _ensure_write_allowed("trigger_workflow_dispatch")
    path = f"/repos/{full_name}/actions/workflows/{workflow}/dispatches"
    payload: Dict[str, Any] = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs
    await _github_request("POST", path, json_body=payload)
    return {"status": "triggered", "workflow": workflow, "ref": ref}


@mcp_tool(write_action=True)
async def trigger_and_wait_for_workflow(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """
    Trigger a workflow_dispatch and wait for the resulting run to complete.
    """
    _ensure_write_allowed("trigger_and_wait_for_workflow")

    await trigger_workflow_dispatch(full_name, workflow, ref, inputs)

    resp = await _github_request(
        "GET",
        f"/repos/{full_name}/actions/runs",
        params={"per_page": 5, "branch": ref},
    )
    data = resp.json()
    runs = data.get("workflow_runs", [])
    matching = None
    for r in runs:
        if str(r.get("name")) == str(workflow) or str(r.get("path")).endswith(f"/{workflow}"):
            matching = r
            break

    if not matching:
        raise GitHubAPIError("Could not locate workflow run after dispatch")

    run_id = matching.get("id")
    result = await wait_for_workflow_run(
        full_name,
        run_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    return {"workflow": workflow, "ref": ref, "result": result}


# --------------------------------------------------------------------
# Tools: PR / issues
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def list_pull_requests(
    full_name: str,
    state: str = "open",
    head: Optional[str] = None,
    base: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
    if head:
        params["head"] = head
    if base:
        params["base"] = base
    resp = await _github_request("GET", f"/repos/{full_name}/pulls", params=params)
    prs = resp.json()
    return {
        "pull_requests": [
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "head": (pr.get("head") or {}).get("ref"),
                "base": (pr.get("base") or {}).get("ref"),
                "html_url": pr.get("html_url"),
                "draft": pr.get("draft"),
            }
            for pr in prs
        ]
    }


@mcp_tool(write_action=True)
async def merge_pull_request(
    full_name: str,
    number: int,
    merge_method: str = "squash",
    commit_title: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_write_allowed("merge_pull_request")
    payload: Dict[str, Any] = {"merge_method": merge_method}
    if commit_title is not None:
        payload["commit_title"] = commit_title
    if commit_message is not None:
        payload["commit_message"] = commit_message

    resp = await _github_request(
        "PUT",
        f"/repos/{full_name}/pulls/{number}/merge",
        json_body=payload,
    )
    data = resp.json()
    return {
        "merged": data.get("merged"),
        "message": data.get("message"),
        "sha": data.get("sha"),
    }


@mcp_tool(write_action=True)
async def close_pull_request(full_name: str, number: int) -> Dict[str, Any]:
    _ensure_write_allowed("close_pull_request")
    resp = await _github_request(
        "PATCH",
        f"/repos/{full_name}/pulls/{number}",
        json_body={"state": "closed"},
    )
    data = resp.json()
    return {
        "number": data.get("number"),
        "state": data.get("state"),
        "title": data.get("title"),
        "html_url": data.get("html_url"),
    }


@mcp_tool(write_action=True)
async def comment_on_pull_request(
    full_name: str,
    number: int,
    body: str,
) -> Dict[str, Any]:
    _ensure_write_allowed("comment_on_pull_request")
    resp = await _github_request(
        "POST",
        f"/repos/{full_name}/issues/{number}/comments",
        json_body={"body": body},
    )
    data = resp.json()
    return {
        "id": data.get("id"),
        "body": data.get("body"),
        "user": (data.get("user") or {}).get("login"),
        "html_url": data.get("html_url"),
    }


@mcp_tool(write_action=False)
async def compare_refs(
    full_name: str,
    base: str,
    head: str,
) -> Dict[str, Any]:
    resp = await _github_request("GET", f"/repos/{full_name}/compare/{base}...{head}")
    data = resp.json()
    files = data.get("files", []) or []
    trimmed_files = []
    for f in files[:100]:
        patch = f.get("patch")
        if patch and len(patch) > 8000:
            patch = patch[:8000] + "\n...[truncated]"
        trimmed_files.append(
            {
                "filename": f.get("filename"),
                "status": f.get("status"),
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
                "changes": f.get("changes"),
                "patch": patch,
            }
        )
    return {
        "status": data.get("status"),
        "ahead_by": data.get("ahead_by"),
        "behind_by": data.get("behind_by"),
        "total_commits": data.get("total_commits"),
        "html_url": data.get("html_url"),
        "files": trimmed_files,
    }


# --------------------------------------------------------------------
# Tools: Branch / commit / PR helpers
# --------------------------------------------------------------------

async def _get_branch_sha(full_name: str, ref: str) -> str:
    resp = await _github_request("GET", f"/repos/{full_name}/git/ref/heads/{ref}")
    data = resp.json()
    obj = data.get("object") or {}
    sha = obj.get("sha")
    if not sha:
        raise GitHubAPIError(f"Could not resolve ref {ref} in {full_name}")
    return sha


async def _resolve_file_sha(full_name: str, path: str, branch: str) -> Optional[str]:
    try:
        data = await _decode_github_content(full_name, path, ref=branch)
        return data.get("sha")
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
    content_b64 = base64.b64encode(body_bytes).decode("ascii")
    payload: Dict[str, Any] = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    if sha is not None:
        payload["sha"] = sha

    resp = await _github_request(
        "PUT",
        f"/repos/{full_name}/contents/{path}",
        json_body=payload,
    )
    data = resp.json()
    commit = data.get("commit") or {}
    content = data.get("content") or {}
    return {
        "commit_sha": (commit.get("sha")),
        "path": content.get("path"),
        "html_url": content.get("html_url"),
    }


@mcp_tool(write_action=True)
async def create_branch(
    full_name: str,
    new_branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    _ensure_write_allowed("create_branch")
    sha = await _get_branch_sha(full_name, from_ref)
    resp = await _github_request(
        "POST",
        f"/repos/{full_name}/git/refs",
        json_body={"ref": f"refs/heads/{new_branch}", "sha": sha},
    )
    data = resp.json()
    return {"ref": data.get("ref"), "sha": (data.get("object") or {}).get("sha")}


@mcp_tool(write_action=True)
async def ensure_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    _ensure_write_allowed("ensure_branch")
    try:
        sha = await _get_branch_sha(full_name, branch)
        existed = True
    except GitHubAPIError:
        sha = await _get_branch_sha(full_name, from_ref)
        resp = await _github_request(
            "POST",
            f"/repos/{full_name}/git/refs",
            json_body={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        data = resp.json()
        sha = (data.get("object") or {}).get("sha")
        existed = False
    return {"branch": branch, "sha": sha, "existed": existed}


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
    """
    Schedule a file commit in the background and return quickly.
    """
    _ensure_write_allowed("commit_file_async")

    if (content is None and content_url is None) or (content is not None and content_url is not None):
        raise GitHubAPIError("Exactly one of 'content' or 'content_url' must be provided")

    async def _do_commit():
        try:
            if content_url is not None:
                ext_client = await _external_client_instance()
                resp = await ext_client.get(content_url)
                resp.raise_for_status()
                body_bytes = resp.content
            else:
                body_bytes = content.encode("utf-8")
            effective_sha = sha
            if effective_sha is None:
                effective_sha = await _resolve_file_sha(full_name, path, branch)
            await _perform_github_commit(full_name, path, message, body_bytes, branch, effective_sha)
        except Exception as exc:
            print(f"[commit_file_async] Error committing {path}: {exc}", flush=True)

    asyncio.create_task(_do_commit())
    return {"scheduled": True, "path": path, "branch": branch, "message": message}


@mcp_tool(write_action=True)
async def create_pull_request(
    full_name: str,
    title: str,
    head: str,
    base: str = "main",
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    _ensure_write_allowed("create_pull_request")
    payload: Dict[str, Any] = {
        "title": title,
        "head": head,
        "base": base,
        "draft": draft,
    }
    if body is not None:
        payload["body"] = body

    resp = await _github_request(
        "POST",
        f"/repos/{full_name}/pulls",
        json_body=payload,
    )
    data = resp.json()
    return {
        "number": data.get("number"),
        "title": data.get("title"),
        "state": data.get("state"),
        "html_url": data.get("html_url"),
        "draft": data.get("draft"),
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
    """
    Update multiple files on a branch and open a PR.
    """
    _ensure_write_allowed("update_files_and_open_pr")

    branch = new_branch or f"ally-{secrets.token_hex(4)}"
    await ensure_branch(full_name, branch, from_ref=base_branch)

    for f in files:
        path = f.get("path")
        message = f.get("message") or f"Update {path}"
        content = f.get("content")
        content_url = f.get("content_url")
        if (content is None and content_url is None) or (content is not None and content_url is not None):
            raise GitHubAPIError(
                f"File spec for {path} must have exactly one of 'content' or 'content_url'"
            )
        existing_sha = await _resolve_file_sha(full_name, path, branch)
        if content_url is not None:
            ext_client = await _external_client_instance()
            resp = await ext_client.get(content_url)
            resp.raise_for_status()
            body_bytes = resp.content
        else:
            body_bytes = content.encode("utf-8")
        await _perform_github_commit(full_name, path, message, body_bytes, branch, existing_sha)

    pr = await create_pull_request(
        full_name=full_name,
        title=title,
        head=branch,
        base=base_branch,
        body=body,
        draft=draft,
    )
    return {"branch": branch, "pull_request": pr}


# --------------------------------------------------------------------
# Tools: Workspace / "full environment"
# --------------------------------------------------------------------

@mcp_tool(write_action=True)
async def run_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Clone the repo at ref and run a shell command, returning stdout/stderr.
    """
    _ensure_write_allowed("run_command")
    repo_dir = await _clone_repo(full_name, ref=ref)
    try:
        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)
        result = await _run_shell(command, cwd=cwd, timeout_seconds=timeout_seconds)
        return {
            "repo_dir": repo_dir,
            "command": command,
            "result": result,
        }
    finally:
        await _cleanup_dir(repo_dir)


@mcp_tool(write_action=True)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convenience wrapper around run_command for running tests.
    """
    _ensure_write_allowed("run_tests")
    result = await run_command(
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
    )
    return {
        "command": test_command,
        "result": result["result"],
    }


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
    """
    Apply a unified diff patch, optionally run tests, and open a PR.
    """
    _ensure_write_allowed("apply_patch_and_open_pr")
    repo_dir = await _clone_repo(full_name, ref=base_branch)
    branch = new_branch or f"ally-patch-{secrets.token_hex(4)}"

    try:
        result_checkout = await _run_shell(f"git checkout -b {branch}", cwd=repo_dir, timeout_seconds=120)
        if result_checkout["exit_code"] != 0:
            raise GitHubAPIError(f"git checkout failed: {result_checkout}")

        patch_path = os.path.join(repo_dir, "mcp_patch.diff")
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(patch)

        apply_result = await _run_shell(
            f"git apply --whitespace=nowarn {patch_path}",
            cwd=repo_dir,
            timeout_seconds=300,
        )
        if apply_result["exit_code"] != 0:
            raise GitHubAPIError(f"git apply failed: {apply_result}")

        commit_result = await _run_shell(
            f'git commit -am "{title}"',
            cwd=repo_dir,
            timeout_seconds=300,
        )
        if commit_result["exit_code"] != 0:
            raise GitHubAPIError(f"git commit failed: {commit_result}")

        tests_result: Optional[Dict[str, Any]] = None
        if run_tests_flag:
            tests_result = await _run_shell(
                test_command,
                cwd=repo_dir,
                timeout_seconds=test_timeout_seconds,
            )
            if tests_result["exit_code"] != 0 or tests_result["timed_out"]:
                return {"branch": branch, "tests": tests_result, "pull_request": None}

        token = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN must be set for git push")

        push_url = f"https://x-access-token:{token}@github.com/{full_name}.git"
        push_result = await _run_shell(
            f"git push {push_url} {branch}",
            cwd=repo_dir,
            timeout_seconds=600,
        )
        if push_result["exit_code"] != 0:
            raise GitHubAPIError(f"git push failed: {push_result}")

        pr = await create_pull_request(
            full_name=full_name,
            title=title,
            head=branch,
            base=base_branch,
            body=body,
            draft=draft,
        )
        return {"branch": branch, "tests": tests_result, "pull_request": pr}
    finally:
        await _cleanup_dir(repo_dir)


# --------------------------------------------------------------------
# ASGI / Starlette
# --------------------------------------------------------------------

async def _healthz(request: Request) -> Response:
    return PlainTextResponse("OK")


async def _root(request: Request) -> Response:
    return PlainTextResponse("GitHub MCP server is running")


routes = [
    Route("/", _root),
    Route("/healthz", _healthz),
    # Mount the FastMCP SSE server to provide /sse and /messages endpoints
    Mount("/", app=mcp.sse_app()),
]

app = Starlette(debug=False, routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_event():
    await _close_clients()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
