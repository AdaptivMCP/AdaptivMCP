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
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
import uvicorn

from fastmcp import FastMCP  # FastMCP server; mcp_tool is defined below


# --------------------------------------------------------------------
# Configuration / environment
# --------------------------------------------------------------------

GITHUB_API_URL = "https://api.github.com"
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_PAT or GITHUB_TOKEN must be set")

HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", "150"))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "300"))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "200"))
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "80"))
FETCH_FILES_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", str(MAX_CONCURRENCY)))

TOOL_STDOUT_MAX_CHARS = int(os.environ.get("TOOL_STDOUT_MAX_CHARS", "12000"))

# Global flag to gate write actions
WRITE_ALLOWED = bool(int(os.environ.get("GITHUB_MCP_AUTO_APPROVE", "0")))


# --------------------------------------------------------------------
# HTTP clients (GitHub and external)
# --------------------------------------------------------------------

_github_client: Optional[httpx.AsyncClient] = None
_external_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def _github_client_instance() -> httpx.AsyncClient:
    global _github_client
    if _github_client is None:
        async with _client_lock:
            if _github_client is None:
                limits = httpx.Limits(
                    max_connections=HTTPX_MAX_CONNECTIONS,
                    max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
                )
                _github_client = httpx.AsyncClient(
                    base_url=GITHUB_API_URL,
                    headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
                    timeout=HTTPX_TIMEOUT,
                    limits=limits,
                    http2=bool(int(os.environ.get("HTTPX_HTTP2", "1"))),
                )
    return _github_client


async def _external_client_instance() -> httpx.AsyncClient:
    global _external_client
    if _external_client is None:
        async with _client_lock:
            if _external_client is None:
                limits = httpx.Limits(
                    max_connections=HTTPX_MAX_CONNECTIONS,
                    max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
                )
                _external_client = httpx.AsyncClient(
                    timeout=HTTPX_TIMEOUT,
                    limits=limits,
                    http2=bool(int(os.environ.get("HTTPX_HTTP2", "1"))),
                )
    return _external_client


async def _close_clients() -> None:
    global _github_client, _external_client
    if _github_client is not None:
        await _github_client.aclose()
        _github_client = None
    if _external_client is not None:
        await _external_client.aclose()
        _external_client = None


# --------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------

class GitHubAPIError(Exception):
    pass


class GitHubAuthError(Exception):
    pass


# --------------------------------------------------------------------
# FastMCP server and tool decorator
# --------------------------------------------------------------------

mcp = FastMCP("GitHub Fast MCP")

# Track write_action metadata in a separate registry keyed by function name.
TOOL_WRITE_ACTIONS: Dict[str, bool] = {}


def mcp_tool(write_action: bool = False):
    """
    Decorator that wraps mcp.tool and records whether the tool is a write action.

    We cannot set arbitrary attributes on the FastMCP FunctionTool objects because
    they are Pydantic models with fixed fields. Instead, we maintain a separate
    dictionary mapping tool names to their write_action flag.
    """

    def decorator(func):
        # Register the tool with FastMCP
        tool = mcp.tool()(func)
        # Record the write_action metadata keyed by the underlying function name
        TOOL_WRITE_ACTIONS[func.__name__] = bool(write_action)
        return tool

    return decorator


# Helper used by tools to check write permissions
async def _ensure_github_auth() -> None:
    if not GITHUB_TOKEN:
        raise GitHubAuthError("GitHub token not configured")


def _ensure_write_allowed(context: str):
    if not WRITE_ALLOWED:
        raise GitHubAPIError(f"Write tools are not authorized for this session (context: {context})")


# --------------------------------------------------------------------
# GitHub helpers
# --------------------------------------------------------------------

async def _github_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    await _ensure_github_auth()
    client = await _github_client_instance()
    resp = await client.get(path, params=params)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub GET {path} failed: {resp.status_code} {resp.text}")
    return resp.json()


async def _github_post(path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
    await _ensure_github_auth()
    client = await _github_client_instance()
    resp = await client.post(path, json=json_body)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub POST {path} failed: {resp.status_code} {resp.text}")
    return resp.json()


async def _github_put(path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
    await _ensure_github_auth()
    client = await _github_client_instance()
    resp = await client.put(path, json=json_body)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub PUT {path} failed: {resp.status_code} {resp.text}")
    return resp.json()


async def _github_patch(path: str, json_body: Dict[str, Any]) -> Dict[str, Any]:
    await _ensure_github_auth()
    client = await _github_client_instance()
    resp = await client.patch(path, json=json_body)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub PATCH {path} failed: {resp.status_code} {resp.text}")
    return resp.json()


async def _github_delete(path: str) -> Dict[str, Any]:
    await _ensure_github_auth()
    client = await _github_client_instance()
    resp = await client.delete(path)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub DELETE {path} failed: {resp.status_code} {resp.text}")
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code, "text": resp.text}


async def _github_graphql(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    await _ensure_github_auth()
    client = await _github_client_instance()
    resp = await client.post(
        GITHUB_GRAPHQL_URL,
        json={"query": query, "variables": variables or {}},
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub GraphQL failed: {resp.status_code} {resp.text}")
    return resp.json()


async def _decode_github_content(full_name: str, path: str, ref: str = "main") -> Dict[str, Any]:
    """
    Fetch and decode a file's content from GitHub. Returns a small, structured payload
    to avoid blowing up tool responses.

    Response:
      {
        "status": "ok" | "not_found" | "error",
        "text": <decoded text or None>,
        "sha": <blob sha or None>,
        "path": <path>,
        "html_url": <html url to GitHub>,
      }
    """
    await _ensure_github_auth()
    client = await _github_client_instance()
    url = f"/repos/{full_name}/contents/{path}"
    resp = await client.get(url, params={"ref": ref})

    if resp.status_code == 404:
        return {"status": "not_found", "text": None, "sha": None, "path": path, "html_url": None}

    if resp.status_code >= 400:
        return {
            "status": "error",
            "text": None,
            "sha": None,
            "path": path,
            "html_url": None,
            "error": f"{resp.status_code} {resp.text}",
        }

    data = resp.json()
    content = data.get("content", "")
    encoding = data.get("encoding", "base64")
    sha = data.get("sha")
    html_url = data.get("html_url")

    text: Optional[str]
    if encoding == "base64":
        try:
            text = base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception as exc:
            text = f"<<error decoding base64 content: {exc}>>"
    else:
        text = f"<<unsupported encoding: {encoding}>>"

    # Optionally trim very large files
    max_chars = int(os.environ.get("FILE_CONTENT_MAX_CHARS", "6000"))
    if text and len(text) > max_chars:
        text = text[:max_chars] + "\n\n<<truncated>>\n"

    return {"status": "ok", "text": text, "sha": sha, "path": path, "html_url": html_url}


# --------------------------------------------------------------------
# Workspace helpers (shell, clone, cleanup)
# --------------------------------------------------------------------

async def _run_shell(cmd: str, cwd: Optional[str] = None, timeout_seconds: int = 300) -> Dict[str, Any]:
    """
    Run a shell command with timeout and return trimmed stdout/stderr.
    """
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        stdout_bytes, stderr_bytes = b"", b""
        timed_out = True

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if len(stdout) > TOOL_STDOUT_MAX_CHARS:
        stdout = stdout[:TOOL_STDOUT_MAX_CHARS] + "\n\n<<stdout truncated>>\n"
    if len(stderr) > TOOL_STDOUT_MAX_CHARS:
        stderr = stderr[:TOOL_STDOUT_MAX_CHARS] + "\n\n<<stderr truncated>>\n"

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
    }


async def _clone_repo(full_name: str, ref: str = "main") -> str:
    """
    Clone a repo into a temporary directory at a specific ref (branch/tag/sha).
    Returns the path to the cloned repo.
    """
    await _ensure_github_auth()
    tmpdir = tempfile.mkdtemp(prefix="github-mcp-")
    token = urllib.parse.quote(GITHUB_TOKEN, safe="")
    clone_url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    cmd = f"git clone --depth 1 --branch {ref} {clone_url} {tmpdir}"
    result = await _run_shell(cmd, timeout_seconds=600)
    if result["exit_code"] != 0:
        await _cleanup_dir(tmpdir)
        raise GitHubAPIError(f"Failed to clone repo: {result}")
    return tmpdir


async def _cleanup_dir(path: str) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


# --------------------------------------------------------------------
# Basic repo tools
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    """
    Get GitHub API rate limit status for the current token.
    """
    data = await _github_get("/rate_limit")
    return data


@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> Dict[str, Any]:
    """
    Get repository metadata for a repo like 'owner/name'.
    """
    data = await _github_get(f"/repos/{full_name}")
    return data


@mcp_tool(write_action=False)
async def list_branches(full_name: str, per_page: int = 100, page: int = 1) -> Dict[str, Any]:
    """
    List branches in a repository.
    """
    params = {"per_page": per_page, "page": page}
    data = await _github_get(f"/repos/{full_name}/branches", params=params)
    return {"branches": data, "page": page, "per_page": per_page}


@mcp_tool(write_action=False)
async def get_file_contents(full_name: str, path: str, ref: str = "main") -> Dict[str, Any]:
    """
    Get and decode file contents at a specific ref.
    """
    return await _decode_github_content(full_name, path, ref=ref)


@mcp_tool(write_action=False)
async def fetch_files(full_name: str, paths: List[str], ref: str = "main") -> Dict[str, Any]:
    """
    Fetch multiple files in parallel with bounded concurrency.

    Returns structure:
      {
        "results": {
          "<path>": { status, text, sha, path, html_url },
          ...
        }
      }
    """
    semaphore = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def _fetch(path: str) -> Dict[str, Any]:
        async with semaphore:
            return await _decode_github_content(full_name, path, ref=ref)

    tasks = {path: asyncio.create_task(_fetch(path)) for path in paths}
    results: Dict[str, Any] = {}
    for path, task in tasks.items():
        try:
            results[path] = await task
        except Exception as exc:
            results[path] = {
                "status": "error",
                "text": None,
                "sha": None,
                "path": path,
                "html_url": None,
                "error": str(exc),
            }

    return {"results": results, "ref": ref}


@mcp_tool(write_action=False)
async def graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Run a raw GitHub GraphQL query.
    """
    data = await _github_graphql(query, variables)
    return data


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    """
    Fetch an arbitrary URL using the external HTTP client.
    This is useful for retrieving artifacts from sandboxed URLs, etc.
    """
    client = await _external_client_instance()
    try:
        resp = await client.get(url)
        text = resp.text
        if len(text) > TOOL_STDOUT_MAX_CHARS:
            text = text[:TOOL_STDOUT_MAX_CHARS] + "\n\n<<truncated>>\n"
        return {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "text": text,
        }
    except Exception as exc:
        return {"error": str(exc)}


# --------------------------------------------------------------------
# GitHub Actions tools
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def list_workflow_runs(
    full_name: str,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    event: Optional[str] = None,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """
    List GitHub Actions workflow runs for a repository.
    """
    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    if event:
        params["event"] = event

    data = await _github_get(f"/repos/{full_name}/actions/runs", params=params)
    return data


@mcp_tool(write_action=False)
async def get_workflow_run(full_name: str, run_id: int) -> Dict[str, Any]:
    """
    Get a single GitHub Actions workflow run.
    """
    data = await _github_get(f"/repos/{full_name}/actions/runs/{run_id}")
    return data


@mcp_tool(write_action=False)
async def list_workflow_run_jobs(
    full_name: str,
    run_id: int,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """
    List jobs for a workflow run.
    """
    params = {"per_page": per_page, "page": page}
    data = await _github_get(f"/repos/{full_name}/actions/runs/{run_id}/jobs", params=params)
    return data


@mcp_tool(write_action=False)
async def get_job_logs(full_name: str, job_id: int) -> Dict[str, Any]:
    """
    Get logs for a specific job in a workflow run.
    Logs are truncated to avoid huge responses.
    """
    await _ensure_github_auth()
    client = await _github_client_instance()
    url = f"/repos/{full_name}/actions/jobs/{job_id}/logs"
    resp = await client.get(url)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub job logs failed: {resp.status_code} {resp.text}")

    text = resp.text
    max_len = int(os.environ.get("JOB_LOG_MAX_CHARS", "16000"))
    if len(text) > max_len:
        text = text[:max_len] + "\n\n<<truncated>>\n"
    return {"status_code": resp.status_code, "text": text}


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
    while True:
        run = await get_workflow_run(full_name, run_id)
        status = run.get("status")
        conclusion = run.get("conclusion")
        if status == "completed":
            return {"completed": True, "run": run, "conclusion": conclusion}
        if time.time() - start > timeout_seconds:
            return {"completed": False, "timeout": True, "run": run}
        await asyncio.sleep(poll_interval_seconds)


@mcp_tool(write_action=False)
async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Trigger a workflow_dispatch event for a workflow file or ID.
    """
    path = f"/repos/{full_name}/actions/workflows/{workflow}/dispatches"
    body = {"ref": ref}
    if inputs:
        body["inputs"] = inputs
    await _github_post(path, body)
    return {"status": "dispatched", "workflow": workflow, "ref": ref}


@mcp_tool(write_action=False)
async def trigger_and_wait_for_workflow(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """
    Trigger a workflow and wait for its completion.
    """
    # First trigger by creating a new run
    await trigger_workflow_dispatch(full_name, workflow, ref, inputs)

    # Then poll for the most recent run on this branch and workflow file
    start_time = time.time()
    last_run: Optional[Dict[str, Any]] = None
    run_id: Optional[int] = None

    while run_id is None and time.time() - start_time < timeout_seconds:
        runs = await list_workflow_runs(full_name, branch=ref, per_page=5, page=1)
        for run in runs.get("workflow_runs", []):
            if run.get("name") == workflow or str(run.get("run_number")) == str(workflow):
                run_id = run.get("id")
                last_run = run
                break
        if run_id is None:
            await asyncio.sleep(poll_interval_seconds)

    if run_id is None:
        return {"error": "no_run_found", "workflow": workflow, "ref": ref, "last_run": last_run}

    waited = await wait_for_workflow_run(full_name, run_id, timeout_seconds=timeout_seconds, poll_interval_seconds=poll_interval_seconds)
    return {"run_id": run_id, "result": waited}


# --------------------------------------------------------------------
# PR / issue management tools
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
    """
    List pull requests for a repository.
    """
    params: Dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
    if head:
        params["head"] = head
    if base:
        params["base"] = base

    data = await _github_get(f"/repos/{full_name}/pulls", params=params)
    return {"pull_requests": data, "page": page, "per_page": per_page}


@mcp_tool(write_action=True)
async def merge_pull_request(
    full_name: str,
    number: int,
    merge_method: str = "squash",
    commit_title: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Merge a pull request. This is a write action.
    """
    _ensure_write_allowed("merge_pull_request")
    path = f"/repos/{full_name}/pulls/{number}/merge"
    body: Dict[str, Any] = {"merge_method": merge_method}
    if commit_title:
        body["commit_title"] = commit_title
    if commit_message:
        body["commit_message"] = commit_message
    data = await _github_put(path, body)
    return data


@mcp_tool(write_action=True)
async def close_pull_request(full_name: str, number: int) -> Dict[str, Any]:
    """
    Close a pull request without merging. This is a write action.
    """
    _ensure_write_allowed("close_pull_request")
    path = f"/repos/{full_name}/pulls/{number}"
    body = {"state": "closed"}
    data = await _github_patch(path, body)
    return data


@mcp_tool(write_action=True)
async def comment_on_pull_request(full_name: str, number: int, body: str) -> Dict[str, Any]:
    """
    Comment on a pull request. This is a write action.
    """
    _ensure_write_allowed("comment_on_pull_request")
    path = f"/repos/{full_name}/issues/{number}/comments"
    data = await _github_post(path, {"body": body})
    return data


@mcp_tool(write_action=False)
async def compare_refs(full_name: str, base: str, head: str) -> Dict[str, Any]:
    """
    Compare two refs in a repository.

    Returns:
      {
        "summary": {...},
        "files": [ up to 100 files, with truncated patch text ],
      }
    """
    data = await _github_get(f"/repos/{full_name}/compare/{base}...{head}")
    files = data.get("files", [])[:100]
    max_patch_chars = int(os.environ.get("COMPARE_PATCH_MAX_CHARS", "8000"))

    processed_files = []
    for f in files:
        patch = f.get("patch")
        if patch and len(patch) > max_patch_chars:
            patch = patch[:max_patch_chars] + "\n\n<<patch truncated>>\n"
        processed_files.append(
            {
                "filename": f.get("filename"),
                "status": f.get("status"),
                "additions": f.get("additions"),
                "deletions": f.get("deletions"),
                "changes": f.get("changes"),
                "patch": patch,
            }
        )

    summary = {
        "total_commits": data.get("total_commits"),
        "behind_by": data.get("behind_by"),
        "ahead_by": data.get("ahead_by"),
        "status": data.get("status"),
    }
    return {"summary": summary, "files": processed_files}


# --------------------------------------------------------------------
# Branch / commit / PR helpers and tools
# --------------------------------------------------------------------

async def _get_branch_sha(full_name: str, ref: str) -> str:
    """
    Resolve a branch or tag to a commit SHA.
    """
    data = await _github_get(f"/repos/{full_name}/git/ref/heads/{ref}")
    obj = data.get("object") or {}
    sha = obj.get("sha")
    if not sha:
        raise GitHubAPIError(f"Could not resolve ref {ref} in {full_name}")
    return sha


async def _resolve_file_sha(full_name: str, path: str, branch: str) -> Optional[str]:
    """
    Resolve the SHA for a file in a branch, or None if not found.
    """
    await _ensure_github_auth()
    client = await _github_client_instance()
    resp = await client.get(f"/repos/{full_name}/contents/{path}", params={"ref": branch})
    if resp.status_code == 404:
        return None
    if resp.status_code >= 400:
        raise GitHubAPIError(f"Failed to resolve file SHA: {resp.status_code} {resp.text}")
    data = resp.json()
    return data.get("sha")


async def _perform_github_commit(
    full_name: str,
    path: str,
    message: str,
    body_bytes: bytes,
    branch: str,
    sha: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Thin wrapper around PUT /repos/{full_name}/contents/{path}
    """
    await _ensure_github_auth()
    client = await _github_client_instance()
    url = f"/repos/{full_name}/contents/{path}"
    content_b64 = base64.b64encode(body_bytes).decode("ascii")
    payload: Dict[str, Any] = {
        "message": message,
        "content": content_b64,
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    resp = await client.put(url, json=payload)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub commit failed: {resp.status_code} {resp.text}")
    return resp.json()


@mcp_tool(write_action=True)
async def create_branch(full_name: str, new_branch: str, from_ref: str = "main") -> Dict[str, Any]:
    """
    Create a new branch from an existing ref. This is a write action.
    """
    _ensure_write_allowed("create_branch")
    sha = await _get_branch_sha(full_name, from_ref)
    path = f"/repos/{full_name}/git/refs"
    body = {"ref": f"refs/heads/{new_branch}", "sha": sha}
    data = await _github_post(path, body)
    return data


@mcp_tool(write_action=True)
async def ensure_branch(full_name: str, branch: str, from_ref: str = "main") -> Dict[str, Any]:
    """
    Ensure a branch exists. If not, create it from from_ref.
    """
    _ensure_write_allowed("ensure_branch")
    await _ensure_github_auth()
    client = await _github_client_instance()
    ref_path = f"/repos/{full_name}/git/ref/heads/{branch}"
    resp = await client.get(ref_path)
    if resp.status_code == 200:
        return {"created": False, "branch": branch}

    if resp.status_code != 404:
        raise GitHubAPIError(f"Failed to check branch {branch}: {resp.status_code} {resp.text}")

    sha = await _get_branch_sha(full_name, from_ref)
    create_body = {"ref": f"refs/heads/{branch}", "sha": sha}
    data = await _github_post("/repos/{full_name}/git/refs".format(full_name=full_name), create_body)
    return {"created": True, "branch": branch, "ref": data}


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
    Commit a single file asynchronously. This is a write action.

    Exactly one of `content` or `content_url` must be provided.

    The commit is scheduled as a background asyncio task to avoid long-running
    HTTP calls blocking tool responses.
    """
    _ensure_write_allowed("commit_file_async")

    if (content is None) == (content_url is None):
        raise ValueError("Exactly one of `content` or `content_url` must be provided")

    if content_url is not None:
        client = await _external_client_instance()
        resp = await client.get(content_url)
        if resp.status_code >= 400:
            raise GitHubAPIError(f"Failed to fetch content_url: {resp.status_code} {resp.text}")
        body_bytes = resp.content
    else:
        body_bytes = content.encode("utf-8")

    # Auto-resolve sha if not provided
    if sha is None:
        sha = await _resolve_file_sha(full_name, path, branch)

    async def _do_commit():
        try:
            await _perform_github_commit(
                full_name=full_name,
                path=path,
                message=message,
                body_bytes=body_bytes,
                branch=branch,
                sha=sha,
            )
        except Exception as exc:
            # Log the error to stderr; we can't surface it back to the client after response
            print(f"[commit_file_async] error committing {path} on {branch}: {exc}", flush=True)

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
    """
    Create a pull request. This is a write action.
    """
    _ensure_write_allowed("create_pull_request")
    path = f"/repos/{full_name}/pulls"
    payload: Dict[str, Any] = {
        "title": title,
        "head": head,
        "base": base,
        "draft": draft,
    }
    if body:
        payload["body"] = body

    data = await _github_post(path, payload)
    return data


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

    `files` is a list of dicts like:
      {
        "path": "path/to/file",
        "message": "Commit message",
        "content": "<string>",              # optional
        "content_url": "https://...",       # optional, mutually exclusive with content
      }
    """
    _ensure_write_allowed("update_files_and_open_pr")

    if new_branch is None:
        new_branch = f"ally/update-{uuid.uuid4().hex[:8]}"

    # Ensure branch exists
    branch_info = await ensure_branch(full_name, new_branch, from_ref=base_branch)

    # Commit each file
    for f in files:
        path = f.get("path")
        msg = f.get("message") or title
        content = f.get("content")
        content_url = f.get("content_url")
        if not path:
            raise ValueError("Each file must have a 'path' key")
        if (content is None) == (content_url is None):
            raise ValueError("Each file must provide exactly one of 'content' or 'content_url'")

        await commit_file_async(
            full_name=full_name,
            path=path,
            message=msg,
            content=content,
            content_url=content_url,
            branch=new_branch,
        )

    # Open PR
    pr = await create_pull_request(
        full_name=full_name,
        title=title,
        head=new_branch,
        base=base_branch,
        body=body,
        draft=draft,
    )
    return {"branch": new_branch, "pull_request": pr, "branch_info": branch_info}


# --------------------------------------------------------------------
# Workspace tools (run_command / run_tests / apply_patch_and_open_pr)
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
    Clone the repo at `ref`, run a shell command, and return stdout/stderr.

    This is marked as a write action because it can run arbitrary commands in a
    cloned environment.
    """
    _ensure_write_allowed("run_command")
    repo_dir = await _clone_repo(full_name, ref=ref)
    try:
        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)
        result = await _run_shell(command, cwd=cwd, timeout_seconds=timeout_seconds)
        return {"repo_dir": repo_dir, "result": result}
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
    return result


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
    Apply a unified diff patch to a repo, optionally run tests, and open a PR.
    """
    _ensure_write_allowed("apply_patch_and_open_pr")

    repo_dir = await _clone_repo(full_name, ref=base_branch)
    if new_branch is None:
        new_branch = f"ally-patch-{secrets.token_hex(4)}"
    branch = new_branch

    try:
        # Create branch
        result = await _run_shell(f"git checkout -b {branch}", cwd=repo_dir, timeout_seconds=60)
        if result["exit_code"] != 0:
            raise GitHubAPIError(f"Failed to create branch {branch}: {result}")

        # Write patch file
        patch_path = os.path.join(repo_dir, "mcp_patch.diff")
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(patch)

        # Apply patch
        apply_result = await _run_shell(
            f"git apply --whitespace=nowarn {patch_path}",
            cwd=repo_dir,
            timeout_seconds=120,
        )
        if apply_result["exit_code"] != 0:
            return {
                "branch": branch,
                "error": "patch_apply_failed",
                "apply_result": apply_result,
            }

        # Commit changes
        commit_result = await _run_shell(
            f'git commit -am "{title}"',
            cwd=repo_dir,
            timeout_seconds=120,
        )
        if commit_result["exit_code"] != 0:
            return {
                "branch": branch,
                "error": "commit_failed",
                "commit_result": commit_result,
            }

        tests_result: Optional[Dict[str, Any]] = None
        if run_tests_flag:
            tests_result = await _run_shell(
                test_command,
                cwd=repo_dir,
                timeout_seconds=test_timeout_seconds,
            )
            if tests_result["exit_code"] != 0 or tests_result["timed_out"]:
                return {
                    "branch": branch,
                    "tests": tests_result,
                    "pull_request": None,
                }

        # Push branch
        token = urllib.parse.quote(GITHUB_TOKEN, safe="")
        push_url = f"https://x-access-token:{token}@github.com/{full_name}.git"
        await _run_shell(
            f"git push {push_url} {branch}",
            cwd=repo_dir,
            timeout_seconds=120,
        )

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
# Write gating control tool
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    """
    Enable or disable all write_action tools for the session.
    """
    global WRITE_ALLOWED
    WRITE_ALLOWED = bool(approved)
    return {"write_actions_enabled": WRITE_ALLOWED}


# --------------------------------------------------------------------
# ASGI / Starlette
# --------------------------------------------------------------------

# FastMCP HTTP app (streamable HTTP transport).
# This exposes the MCP JSON-RPC interface under the /mcp path prefix.
mcp_http_app = mcp.http_app(path="/")


async def _healthz(request: Request) -> Response:
    return PlainTextResponse("OK")


async def _root(request: Request) -> Response:
    return PlainTextResponse("GitHub MCP server is running")


routes = [
    Route("/", _root),
    Route("/healthz", _healthz),
    # Mount the FastMCP HTTP app under /mcp
    Mount("/mcp", app=mcp_http_app),
]

app = Starlette(
    debug=False,
    routes=routes,
    lifespan=mcp_http_app.lifespan,
)

# Allow cross-origin requests (needed for MCP over HTTP from hosted clients)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await _close_clients()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
