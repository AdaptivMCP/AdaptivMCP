import os
import asyncio
import base64
import tempfile
import secrets
import shutil
import textwrap
import urllib.parse
from typing import Optional, Dict, Any, List

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route, Mount
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# MCP framework
from fastmcp import FastMCP  # FastMCP server; mcp_tool is defined below


# --------------------------------------------------------------------
# Environment and constants
# --------------------------------------------------------------------

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", "150"))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "300"))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "200"))
HTTPX_HTTP2 = bool(int(os.environ.get("HTTPX_HTTP2", "1")))
MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", "80"))
FETCH_FILES_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", str(MAX_CONCURRENCY)))
TOOL_STDOUT_MAX_CHARS = int(os.environ.get("TOOL_STDOUT_MAX_CHARS", "12000"))
TOOL_STDERR_MAX_CHARS = int(os.environ.get("TOOL_STDERR_MAX_CHARS", "12000"))

GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise RuntimeError("GITHUB_PAT or GITHUB_TOKEN must be set for GitHub authentication")


class GitHubAPIError(Exception):
    pass


class GitHubAuthError(Exception):
    pass


# --------------------------------------------------------------------
# Shared HTTPX clients
# --------------------------------------------------------------------

_httpx_github_client: Optional[httpx.AsyncClient] = None
_httpx_external_client: Optional[httpx.AsyncClient] = None


def _github_client_instance() -> httpx.AsyncClient:
    global _httpx_github_client
    if _httpx_github_client is None:
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        _httpx_github_client = httpx.AsyncClient(
            base_url=GITHUB_API_BASE.rstrip("/"),
            headers=headers,
            timeout=HTTPX_TIMEOUT,
            limits=httpx.Limits(
                max_connections=HTTPX_MAX_CONNECTIONS,
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
            ),
            http2=HTTPX_HTTP2,
        )
    return _httpx_github_client


def _external_client_instance() -> httpx.AsyncClient:
    global _httpx_external_client
    if _httpx_external_client is None:
        _httpx_external_client = httpx.AsyncClient(
            timeout=HTTPX_TIMEOUT,
            limits=httpx.Limits(
                max_connections=HTTPX_MAX_CONNECTIONS,
                max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
            ),
            http2=HTTPX_HTTP2,
        )
    return _httpx_external_client


async def _close_clients():
    global _httpx_github_client, _httpx_external_client
    if _httpx_github_client is not None:
        await _httpx_github_client.aclose()
        _httpx_github_client = None
    if _httpx_external_client is not None:
        await _httpx_external_client.aclose()
        _httpx_external_client = None


# --------------------------------------------------------------------
# MCP server + decorator
# --------------------------------------------------------------------

mcp = FastMCP("GitHub Fast MCP", json_response=True)

# Initialize write gating from env: if GITHUB_MCP_AUTO_APPROVE=1, enable writes by default.
AUTO_APPROVE = bool(int(os.environ.get("GITHUB_MCP_AUTO_APPROVE", "0")))
WRITE_ALLOWED = AUTO_APPROVE


def mcp_tool(*tool_args, write_action: bool = False, **tool_kwargs):
    """
    Decorator that wraps mcp.tool and attaches write_action metadata
    so clients can distinguish read vs write tools.
    """
    def decorator(func):
        # Use FastMCP's native decorator to register the tool, but keep the
        # underlying callable so it can still be invoked internally.
        decorated = mcp.tool(*tool_args, **tool_kwargs)(func)
        # Attach metadata to the function object (not the Pydantic FunctionTool model).
        setattr(decorated, "write_action", write_action)
        return decorated
    return decorator


@mcp_tool(write_action=False)
async def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    """
    Explicitly enable or disable write actions for the current process.
    If GITHUB_MCP_AUTO_APPROVE=1, WRITE_ALLOWED starts as True and this
    function can still be used to turn writes off or re-enable them.
    """
    global WRITE_ALLOWED
    WRITE_ALLOWED = bool(approved)
    return {"write_actions_enabled": WRITE_ALLOWED}


def _ensure_write_allowed(context: str):
    if not WRITE_ALLOWED:
        raise GitHubAPIError(f"Write tools are not authorized for this session (context: {context})")


# --------------------------------------------------------------------
# GitHub helpers
# --------------------------------------------------------------------

async def _github_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = _github_client_instance()
    url = f"{GITHUB_API_BASE.rstrip('/')}{path}"
    resp = await client.request(method, url, params=params, json=json_body)
    if resp.status_code >= 400:
        try:
            data = resp.json()
        except Exception:
            data = None
        message = data.get("message") if isinstance(data, dict) else None
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for {method} {path}: {message or resp.text}"
        )
    return {"status_code": resp.status_code, "json": resp.json(), "raw": resp}


async def _decode_github_content(
    full_name: str,
    path: str,
    ref: str = "main",
) -> Dict[str, Any]:
    client = _github_client_instance()
    url = f"/repos/{full_name}/contents/{path}"
    resp = await client.get(url, params={"ref": ref})
    if resp.status_code == 404:
        raise GitHubAPIError(f"File not found: {full_name}/{path}@{ref}")
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for GET {url}: {resp.text}"
        )
    data = resp.json()
    content = data.get("content")
    if data.get("encoding") == "base64" and content is not None:
        decoded = base64.b64decode(content).decode("utf-8", errors="replace")
    else:
        decoded = ""
    return {
        "status_code": resp.status_code,
        "text": decoded,
        "sha": data.get("sha"),
        "path": data.get("path"),
        "html_url": data.get("html_url"),
    }


async def _run_shell(
    cmd: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 300,
) -> Dict[str, Any]:
    """
    Run a shell command with a timeout, trimming stdout/stderr to avoid
    huge MCP responses.
    """
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout_seconds,
        )
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        stdout_bytes, stderr_bytes = await proc.communicate()
        timed_out = True

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if len(stdout) > TOOL_STDOUT_MAX_CHARS:
        stdout = stdout[:TOOL_STDOUT_MAX_CHARS] + "\n...[truncated]..."
    if len(stderr) > TOOL_STDERR_MAX_CHARS:
        stderr = stderr[:TOOL_STDERR_MAX_CHARS] + "\n...[truncated]..."

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
    }


async def _clone_repo(full_name: str, ref: str = "main") -> str:
    """
    Clone the given repo at the given ref into a temporary directory.
    """
    if not GITHUB_TOKEN:
        raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN must be set for clone operations")

    tmp_dir = tempfile.mkdtemp(prefix="mcp-github-")
    # Use a shallow clone for speed.
    token = urllib.parse.quote(GITHUB_TOKEN, safe="")
    clone_url = f"https://x-access-token:{token}@github.com/{full_name}.git"
    cmd = f"git clone --depth 1 --branch {ref} {clone_url} {tmp_dir}"
    result = await _run_shell(cmd, timeout_seconds=300)
    if result["exit_code"] != 0:
        await _cleanup_dir(tmp_dir)
        raise GitHubAPIError(f"git clone failed: {result['stderr']}")
    return tmp_dir


async def _cleanup_dir(path: str):
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


# --------------------------------------------------------------------
# Tools: rate limit and repo inspection
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    """
    Get GitHub rate limit status for the configured token.
    """
    data = await _github_request("GET", "/rate_limit")
    return data["json"]


@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> Dict[str, Any]:
    """
    Get basic information about a repository.
    """
    data = await _github_request("GET", f"/repos/{full_name}")
    return data["json"]


@mcp_tool(write_action=False)
async def list_branches(
    full_name: str,
    per_page: int = 100,
    page: int = 1,
) -> Dict[str, Any]:
    """
    List branches in a repository.
    """
    client = _github_client_instance()
    resp = await client.get(
        f"/repos/{full_name}/branches",
        params={"per_page": per_page, "page": page},
    )
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for list_branches: {resp.text}"
        )
    return {"status_code": resp.status_code, "branches": resp.json()}


@mcp_tool(write_action=False)
async def get_file_contents(
    full_name: str,
    path: str,
    ref: str = "main",
) -> Dict[str, Any]:
    """
    Get and decode the contents of a file from GitHub.
    """
    return await _decode_github_content(full_name, path, ref)


@mcp_tool(write_action=False)
async def fetch_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
) -> Dict[str, Any]:
    """
    Fetch multiple files concurrently, trimming content as needed.
    """
    results: Dict[str, Any] = {}

    sem = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def _fetch_one(p: str):
        async with sem:
            try:
                decoded = await _decode_github_content(full_name, p, ref)
            except GitHubAPIError as e:
                results[p] = {"error": str(e)}
                return
            text = decoded["text"]
            if len(text) > TOOL_STDOUT_MAX_CHARS:
                text = text[:TOOL_STDOUT_MAX_CHARS] + "\n...[truncated]..."
            results[p] = {
                "text": text,
                "sha": decoded["sha"],
                "path": decoded["path"],
                "html_url": decoded["html_url"],
            }

    await asyncio.gather(*[_fetch_one(p) for p in paths])
    return {"files": results}


@mcp_tool(write_action=False)
async def graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Run a GraphQL query against the GitHub API.
    """
    client = _github_client_instance()
    resp = await client.post(
        "/graphql",
        json={"query": query, "variables": variables or {}},
    )
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub GraphQL error {resp.status_code}: {resp.text}"
        )
    return resp.json()


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    """
    Fetch an arbitrary URL (for example, raw file content).
    """
    client = _external_client_instance()
    resp = await client.get(url)
    text = resp.text
    if len(text) > TOOL_STDOUT_MAX_CHARS:
        text = text[:TOOL_STDOUT_MAX_CHARS] + "\n...[truncated]..."
    return {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "text": text,
    }


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
    client = _github_client_instance()
    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    if event:
        params["event"] = event
    resp = await client.get(f"/repos/{full_name}/actions/runs", params=params)
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for list_workflow_runs: {resp.text}"
        )
    return resp.json()


@mcp_tool(write_action=False)
async def get_workflow_run(
    full_name: str,
    run_id: int,
) -> Dict[str, Any]:
    data = await _github_request("GET", f"/repos/{full_name}/actions/runs/{run_id}")
    return data["json"]


@mcp_tool(write_action=False)
async def list_workflow_run_jobs(
    full_name: str,
    run_id: int,
    per_page: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    client = _github_client_instance()
    resp = await client.get(
        f"/repos/{full_name}/actions/runs/{run_id}/jobs",
        params={"per_page": per_page, "page": page},
    )
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for list_workflow_run_jobs: {resp.text}"
        )
    return resp.json()


@mcp_tool(write_action=False)
async def get_job_logs(
    full_name: str,
    job_id: int,
) -> Dict[str, Any]:
    client = _github_client_instance()
    resp = await client.get(f"/repos/{full_name}/actions/jobs/{job_id}/logs")
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for get_job_logs: {resp.text}"
        )
    text = resp.text
    max_chars = 16000
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...[truncated]..."
    return {"status_code": resp.status_code, "text": text}


@mcp_tool(write_action=False)
async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    """
    Poll a workflow run until it completes or times out.
    """
    client = _github_client_instance()
    deadline = asyncio.get_event_loop().time() + timeout_seconds

    while True:
        resp = await client.get(f"/repos/{full_name}/actions/runs/{run_id}")
        if resp.status_code >= 400:
            raise GitHubAPIError(
                f"GitHub API error {resp.status_code} for get_workflow_run: {resp.text}"
            )
        data = resp.json()
        status = data.get("status")
        conclusion = data.get("conclusion")
        if status in ("completed", "failure", "cancelled") or conclusion is not None:
            return data
        if asyncio.get_event_loop().time() >= deadline:
            raise GitHubAPIError(
                f"Timed out waiting for workflow run {run_id} in {full_name}"
            )
        await asyncio.sleep(poll_interval_seconds)


@mcp_tool(write_action=True)
async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Trigger a workflow_dispatch event on a workflow file.
    """
    _ensure_write_allowed(f"trigger_workflow_dispatch {full_name} {workflow}@{ref}")
    path = f"/repos/{full_name}/actions/workflows/{workflow}/dispatches"
    payload = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs
    await _github_request("POST", path, json_body=payload)
    return {"triggered": True}


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
    Trigger a workflow_dispatch workflow and wait for the most recent run
    on that branch.
    """
    _ensure_write_allowed(
        f"trigger_and_wait_for_workflow {full_name} {workflow}@{ref}"
    )
    await trigger_workflow_dispatch(full_name, workflow, ref, inputs)
    client = _github_client_instance()

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    last_run = None
    while True:
        resp = await client.get(
            f"/repos/{full_name}/actions/workflows/{workflow}/runs",
            params={"branch": ref, "per_page": 1},
        )
        if resp.status_code >= 400:
            raise GitHubAPIError(
                f"GitHub API error {resp.status_code} for list_workflow_runs: {resp.text}"
            )
        runs = resp.json().get("workflow_runs", [])
        if runs:
            last_run = runs[0]
            status = last_run.get("status")
            conclusion = last_run.get("conclusion")
            if status in ("completed", "failure", "cancelled") or conclusion is not None:
                return {"run": last_run}
        if asyncio.get_event_loop().time() >= deadline:
            raise GitHubAPIError(
                f"Timed out waiting for workflow {workflow} on {ref} in {full_name}"
            )
        await asyncio.sleep(poll_interval_seconds)


# --------------------------------------------------------------------
# PR / issue management
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
    client = _github_client_instance()
    params: Dict[str, Any] = {"state": state, "per_page": per_page, "page": page}
    if head:
        params["head"] = head
    if base:
        params["base"] = base
    resp = await client.get(f"/repos/{full_name}/pulls", params=params)
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for list_pull_requests: {resp.text}"
        )
    return {"status_code": resp.status_code, "pulls": resp.json()}


@mcp_tool(write_action=True)
async def merge_pull_request(
    full_name: str,
    number: int,
    merge_method: str = "squash",
    commit_title: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"merge_pull_request {full_name} #{number}")
    payload: Dict[str, Any] = {"merge_method": merge_method}
    if commit_title is not None:
        payload["commit_title"] = commit_title
    if commit_message is not None:
        payload["commit_message"] = commit_message
    data = await _github_request(
        "PUT",
        f"/repos/{full_name}/pulls/{number}/merge",
        json_body=payload,
    )
    return data["json"]


@mcp_tool(write_action=True)
async def close_pull_request(
    full_name: str,
    number: int,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"close_pull_request {full_name} #{number}")
    data = await _github_request(
        "PATCH",
        f"/repos/{full_name}/pulls/{number}",
        json_body={"state": "closed"},
    )
    return data["json"]


@mcp_tool(write_action=True)
async def comment_on_pull_request(
    full_name: str,
    number: int,
    body: str,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"comment_on_pull_request {full_name} #{number}")
    data = await _github_request(
        "POST",
        f"/repos/{full_name}/issues/{number}/comments",
        json_body={"body": body},
    )
    return data["json"]


@mcp_tool(write_action=False)
async def compare_refs(
    full_name: str,
    base: str,
    head: str,
) -> Dict[str, Any]:
    """
    Compare two refs, returning a trimmed list of changed files and patches.
    """
    client = _github_client_instance()
    resp = await client.get(f"/repos/{full_name}/compare/{base}...{head}")
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for compare_refs: {resp.text}"
        )
    data = resp.json()
    files = data.get("files", [])[:100]
    trimmed_files = []
    for f in files:
        patch = f.get("patch")
        if patch and len(patch) > 8000:
            patch = patch[:8000] + "\n...[truncated]..."
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
        "files": trimmed_files,
    }


# --------------------------------------------------------------------
# Branch / commit / PR tools
# --------------------------------------------------------------------

async def _get_branch_sha(full_name: str, ref: str) -> str:
    resp = await _github_request("GET", f"/repos/{full_name}/git/ref/heads/{ref}")
    return resp["json"]["object"]["sha"]


@mcp_tool(write_action=True)
async def create_branch(
    full_name: str,
    new_branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    _ensure_write_allowed(f"create_branch {new_branch} from {from_ref}")
    sha = await _get_branch_sha(full_name, from_ref)
    body = {"ref": f"refs/heads/{new_branch}", "sha": sha}
    resp = await _github_request("POST", f"/repos/{full_name}/git/refs", json_body=body)
    return {"ref": resp["json"].get("ref"), "sha": resp["json"].get("object", {}).get("sha")}


@mcp_tool(write_action=True)
async def ensure_branch(
    full_name: str,
    branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    _ensure_write_allowed(f"ensure_branch {branch} from {from_ref}")
    client = _github_client_instance()
    # check if exists
    resp = await client.get(f"/repos/{full_name}/git/ref/heads/{branch}")
    if resp.status_code == 200:
        j = resp.json()
        return {"created": False, "ref": j.get("ref"), "sha": j.get("object", {}).get("sha")}
    if resp.status_code != 404:
        raise GitHubAPIError(f"Failed to check branch {branch}: {resp.status_code} {resp.text}")
    created = await create_branch(full_name, branch, from_ref)
    return {"created": True, **created}


async def _resolve_file_sha(
    full_name: str,
    path: str,
    branch: str,
) -> Optional[str]:
    client = _github_client_instance()
    url = f"{GITHUB_API_BASE.rstrip('/')}/repos/{full_name.strip()}/contents/{path.lstrip('/')}"
    resp = await client.get(url, params={"ref": branch})
    if resp.status_code == 200:
        try:
            existing_json = resp.json()
        except Exception:
            existing_json = {}
        return existing_json.get("sha")
    elif resp.status_code in (404, 410):
        return None
    else:
        raise GitHubAPIError(
            f"Failed to look up existing file {full_name}/{path} for sha: {resp.status_code}"
        )


async def _perform_github_commit(
    full_name: str,
    path: str,
    message: str,
    body_bytes: bytes,
    branch: str,
    sha: Optional[str],
) -> Dict[str, Any]:
    client = _github_client_instance()
    url = f"{GITHUB_API_BASE.rstrip('/')}/repos/{full_name.strip()}/contents/{path.lstrip('/')}"
    encoded = base64.b64encode(body_bytes).decode("ascii")
    json_payload: Dict[str, Any] = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }
    if sha:
        json_payload["sha"] = sha
    resp = await client.put(url, json=json_payload)
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for PUT {url}: {resp.text}"
        )
    return resp.json()


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
    Schedule a GitHub file commit. To keep MCP responses small and avoid
    connector timeouts, this tool returns immediately after scheduling
    the commit in the background.
    """
    _ensure_write_allowed(f"commit_file_async {full_name}/{path}@{branch}")
    if (content is None and content_url is None) or (content is not None and content_url is not None):
        raise GitHubAPIError("Exactly one of 'content' or 'content_url' must be provided")

    if sha is None:
        sha = await _resolve_file_sha(full_name, path, branch)

    if content_url is not None:
        client = _external_client_instance()
        resp = await client.get(content_url)
        if resp.status_code >= 400:
            raise GitHubAPIError(
                f"Failed to fetch content from {content_url}: {resp.status_code} {resp.text}"
            )
        body_bytes = resp.content
    else:
        body_bytes = content.encode("utf-8")

    async def _commit_task():
        try:
            await _perform_github_commit(full_name, path, message, body_bytes, branch, sha)
        except Exception as e:
            # We do not propagate this to the caller to keep the response small.
            print(f"[commit_file_async] Error committing {path}: {e}")

    asyncio.create_task(_commit_task())
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
    _ensure_write_allowed(f"create_pull_request {full_name} {head}->{base}")
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
    return resp["json"]


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
    High-level helper:
    - ensure a branch from base_branch
    - commit multiple files (content or content_url)
    - open a pull request
    """
    _ensure_write_allowed(f"update_files_and_open_pr {title}")
    branch = new_branch or f"ally-{base_branch}-{secrets.token_hex(4)}"
    await ensure_branch(full_name, branch, from_ref=base_branch)

    for f in files:
        path = f["path"]
        file_message = f.get("message") or title
        content = f.get("content")
        content_url = f.get("content_url")
        sha = f.get("sha")

        if (content is None and content_url is None) or (content is not None and content_url is not None):
            raise GitHubAPIError(
                f"For file {path}, exactly one of 'content' or 'content_url' must be provided"
            )

        if sha is None:
            sha = await _resolve_file_sha(full_name, path, branch)

        if content_url is not None:
            client = _external_client_instance()
            resp = await client.get(content_url)
            if resp.status_code >= 400:
                raise GitHubAPIError(
                    f"Failed to fetch content from {content_url}: {resp.status_code} {resp.text}"
                )
            body_bytes = resp.content
        else:
            body_bytes = content.encode("utf-8")

        await _perform_github_commit(full_name, path, file_message, body_bytes, branch, sha)

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
    Clone the repo at the given ref, run a shell command, and clean up.
    """
    _ensure_write_allowed(f"run_command {full_name}@{ref}: {command}")
    repo_dir = await _clone_repo(full_name, ref)
    try:
        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)
        result = await _run_shell(command, cwd=cwd, timeout_seconds=timeout_seconds)
        return {
            "exit_code": result["exit_code"],
            "timed_out": result["timed_out"],
            "stdout": result["stdout"],
            "stderr": result["stderr"],
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
    return await run_command(
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
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
    """
    Apply a unified diff patch to a new branch off base_branch, optionally run tests,
    push to origin, and open a PR.
    """
    _ensure_write_allowed(f"apply_patch_and_open_pr {full_name} {base_branch} {title}")
    repo_dir = await _clone_repo(full_name, base_branch)
    try:
        branch = new_branch or f"ally-patch-{secrets.token_hex(4)}"
        token = urllib.parse.quote(GITHUB_TOKEN, safe="")
        push_url = f"https://x-access-token:{token}@github.com/{full_name}.git"

        # Create and checkout branch
        result = await _run_shell(
            f"git checkout -b {branch}",
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if result["exit_code"] != 0:
            raise GitHubAPIError(f"git checkout -b failed: {result['stderr']}")

        # Write patch to file
        patch_path = os.path.join(repo_dir, "mcp_patch.diff")
        with open(patch_path, "w", encoding="utf-8") as f:
            f.write(patch)

        # Apply patch
        result = await _run_shell(
            "git apply --whitespace=nowarn mcp_patch.diff",
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if result["exit_code"] != 0:
            raise GitHubAPIError(f"git apply failed: {result['stderr']}")

        # Commit changes
        result = await _run_shell(
            'git commit -am "{}"'.format(title.replace('"', '\\"')),
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if result["exit_code"] != 0:
            raise GitHubAPIError(f"git commit failed: {result['stderr']}")

        tests_result = None
        if run_tests_flag:
            tests_result = await _run_shell(
                test_command,
                cwd=repo_dir,
                timeout_seconds=test_timeout_seconds,
            )
            if tests_result["exit_code"] != 0 or tests_result["timed_out"]:
                # Do not push / open PR if tests fail
                return {"branch": branch, "tests": tests_result, "pull_request": None}

        # Push branch
        result = await _run_shell(
            f"git push {push_url} {branch}",
            cwd=repo_dir,
            timeout_seconds=120,
        )
        if result["exit_code"] != 0:
            raise GitHubAPIError(f"git push failed: {result['stderr']}")

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
    # Mount the FastMCP SSE app at the root so /sse and /messages work as expected.
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
