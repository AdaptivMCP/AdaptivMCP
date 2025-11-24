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
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# MCP framework
from fastmcp import FastMCP  # FastMCP server; mcp_tool is defined below


# --------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------

class GitHubAuthError(Exception):
    pass


class GitHubAPIError(Exception):
    pass


# --------------------------------------------------------------------
# Constants / HTTP clients
# --------------------------------------------------------------------

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN environment variable must be set")

_httpx_github_client: Optional[httpx.AsyncClient] = None
_httpx_external_client: Optional[httpx.AsyncClient] = None


def _github_client_instance() -> httpx.AsyncClient:
    global _httpx_github_client
    if _httpx_github_client is None:
        _httpx_github_client = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github+json",
            },
            timeout=float(os.environ.get("HTTPX_TIMEOUT", 60)),
            limits=httpx.Limits(
                max_connections=int(os.environ.get("HTTPX_MAX_CONNECTIONS", 300)),
                max_keepalive_connections=int(os.environ.get("HTTPX_MAX_KEEPALIVE", 200)),
            ),
            http2=bool(int(os.environ.get("HTTPX_HTTP2", "0"))),
        )
    return _httpx_github_client


def _external_client_instance() -> httpx.AsyncClient:
    global _httpx_external_client
    if _httpx_external_client is None:
        _httpx_external_client = httpx.AsyncClient(
            timeout=float(os.environ.get("HTTPX_TIMEOUT", 60)),
            limits=httpx.Limits(
                max_connections=int(os.environ.get("HTTPX_MAX_CONNECTIONS", 100)),
                max_keepalive_connections=int(os.environ.get("HTTPX_MAX_KEEPALIVE", 50)),
            ),
            http2=bool(int(os.environ.get("HTTPX_HTTP2", "0"))),
        )
    return _httpx_external_client


async def _close_clients():
    if _httpx_github_client:
        await _httpx_github_client.aclose()
    if _httpx_external_client:
        await _httpx_external_client.aclose()


# --------------------------------------------------------------------
# MCP server + decorator
# --------------------------------------------------------------------

mcp = FastMCP("GitHub Fast MCP", json_response=True)
WRITE_ALLOWED = False


def mcp_tool(*tool_args, write_action: bool = False, **tool_kwargs):
    """
    Decorator that wraps mcp.tool and attaches write_action metadata
    so clients can distinguish read vs write tools.
    """
    def decorator(func):
        tool = mcp.tool(*tool_args, **tool_kwargs)(func)
        # Attach write_action as metadata instead of setting a new attribute
        # on the FunctionTool Pydantic model (which is not allowed).
        existing_meta = getattr(tool, "meta", None) or {}
        meta = dict(existing_meta)
        meta["write_action"] = write_action
        tool.meta = meta
        return tool

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

async def _github_request(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = _github_client_instance()
    url = path if path.startswith("http") else f"{GITHUB_API_BASE}{path}"
    response = await client.request(method, url, json=json_body, params=params)
    if response.status_code == 401:
        raise GitHubAuthError("GitHub authentication failed: 401")
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub API error {response.status_code}: {response.text}")
    data = response.json()
    return {"status": response.status_code, "json": data}


async def _github_graphql(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client = _github_client_instance()
    response = await client.post("/graphql", json={"query": query, "variables": variables or {}})
    if response.status_code == 401:
        raise GitHubAuthError("GitHub authentication failed: 401 (graphql)")
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub GraphQL error {response.status_code}: {response.text}")
    return response.json()


async def _decode_github_content(full_name: str, path: str, ref: str) -> Dict[str, Any]:
    client = _github_client_instance()
    url = f"/repos/{full_name}/contents/{path}"
    resp = await client.get(url, params={"ref": ref})
    if resp.status_code == 200:
        j = resp.json()
        text = None
        if j.get("encoding") == "base64" and "content" in j:
            try:
                text = base64.b64decode(j["content"]).decode("utf-8", errors="replace")
            except Exception:
                text = None
        return {
            "status": 200,
            "text": text,
            "sha": j.get("sha"),
            "path": j.get("path"),
            "html_url": j.get("html_url"),
        }
    elif resp.status_code in (404, 410):
        return {"status": resp.status_code, "text": None, "sha": None, "path": path, "html_url": None}
    else:
        raise GitHubAPIError(f"Failed to fetch content: {resp.status_code}, body={resp.text}")


# --------------------------------------------------------------------
# Workspace & patch helpers
# --------------------------------------------------------------------

MAX_STDOUT = int(os.environ.get("TOOL_STDOUT_MAX_CHARS", "12000"))
FETCH_FILES_CONCURRENCY = int(
    os.environ.get("FETCH_FILES_CONCURRENCY", os.environ.get("MAX_CONCURRENCY", "256"))
)


async def _run_shell(
    cmd: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    cwd = cwd or os.getcwd()
    proc = await asyncio.create_subprocess_shell(
        cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        timed_out = False
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        stdout, stderr = await proc.communicate()
        timed_out = True

    stdout_text = stdout.decode("utf-8", errors="replace")
    stderr_text = stderr.decode("utf-8", errors="replace")

    if len(stdout_text) > MAX_STDOUT:
        stdout_text = stdout_text[:MAX_STDOUT] + "\n...[truncated stdout]"
    if len(stderr_text) > MAX_STDOUT:
        stderr_text = stderr_text[:MAX_STDOUT] + "\n...[truncated stderr]"

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout_text,
        "stderr": stderr_text,
    }


def _make_clone_url(full_name: str) -> str:
    token_quoted = urllib.parse.quote(GITHUB_TOKEN, safe="")
    return f"https://x-access-token:{token_quoted}@github.com/{full_name}.git"


async def _clone_repo(full_name: str, ref: str) -> str:
    tmpdir = tempfile.mkdtemp(prefix=f"mcp-{full_name.replace('/', '-')}-{secrets.token_hex(4)}-")
    clone_url = _make_clone_url(full_name)
    cmd = f"git clone --depth 1 --branch {ref} {clone_url} {tmpdir}"
    result = await _run_shell(cmd, cwd=None, timeout_seconds=120)
    if result["exit_code"] != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise GitHubAPIError(f"git clone failed: {result['stderr']}")
    return tmpdir


async def _cleanup_dir(path: str):
    try:
        shutil.rmtree(path)
    except Exception:
        pass


def _trim(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n...[truncated]"


# --------------------------------------------------------------------
# Core GitHub tools (read)
# --------------------------------------------------------------------

@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    resp = await _github_request("GET", "/rate_limit")
    return resp["json"]


@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> Dict[str, Any]:
    resp = await _github_request("GET", f"/repos/{full_name}")
    j = resp["json"]
    return {
        "full_name": j.get("full_name"),
        "private": j.get("private"),
        "default_branch": j.get("default_branch"),
        "html_url": j.get("html_url"),
        "description": j.get("description"),
    }


@mcp_tool(write_action=False)
async def list_branches(
    full_name: str,
    per_page: int = 100,
    page: int = 1,
) -> Dict[str, Any]:
    resp = await _github_request(
        "GET",
        f"/repos/{full_name}/branches",
        params={"per_page": per_page, "page": page},
    )
    branches = [
        {
            "name": b.get("name"),
            "protected": b.get("protected"),
            "commit_sha": (b.get("commit") or {}).get("sha"),
        }
        for b in resp["json"]
    ]
    return {"branches": branches}


@mcp_tool(write_action=False)
async def get_file_contents(
    full_name: str,
    path: str,
    ref: str = "main",
) -> Dict[str, Any]:
    result = await _decode_github_content(full_name, path, ref)
    return {
        "status": result["status"],
        "path": path,
        "ref": ref,
        "text": result["text"],
        "sha": result["sha"],
        "html_url": result["html_url"],
    }


@mcp_tool(write_action=False)
async def fetch_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
) -> Dict[str, Any]:
    sem = asyncio.Semaphore(FETCH_FILES_CONCURRENCY)

    async def fetch_one(p: str) -> Dict[str, Any]:
        async with sem:
            try:
                res = await _decode_github_content(full_name, p, ref)
                return {
                    "path": p,
                    "status": res["status"],
                    "text": res["text"],
                    "sha": res["sha"],
                    "html_url": res["html_url"],
                }
            except Exception as e:
                return {"path": p, "error": str(e)}

    tasks = [fetch_one(p) for p in paths]
    results = await asyncio.gather(*tasks)
    return {"ref": ref, "files": results}


@mcp_tool(write_action=False)
async def graphql_query(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result = await _github_graphql(query, variables)
    # Return as-is; caller is responsible for trimming
    return result


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    client = _external_client_instance()
    resp = await client.get(url)
    text = resp.text
    if len(text) > 32000:
        text = text[:32000] + "\n...[truncated body]"
    return {
        "status": resp.status_code,
        "url": str(resp.url),
        "text": text,
        "headers": dict(resp.headers),
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
    runs = []
    for r in resp["json"].get("workflow_runs", []):
        runs.append(
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "event": r.get("event"),
                "status": r.get("status"),
                "conclusion": r.get("conclusion"),
                "head_branch": r.get("head_branch"),
                "html_url": r.get("html_url"),
            }
        )
    return {"workflow_runs": runs}


@mcp_tool(write_action=False)
async def get_workflow_run(
    full_name: str,
    run_id: int,
) -> Dict[str, Any]:
    resp = await _github_request("GET", f"/repos/{full_name}/actions/runs/{run_id}")
    r = resp["json"]
    return {
        "id": r.get("id"),
        "name": r.get("name"),
        "event": r.get("event"),
        "status": r.get("status"),
        "conclusion": r.get("conclusion"),
        "head_branch": r.get("head_branch"),
        "html_url": r.get("html_url"),
    }


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
    jobs = []
    for j in resp["json"].get("jobs", []):
        jobs.append(
            {
                "id": j.get("id"),
                "name": j.get("name"),
                "status": j.get("status"),
                "conclusion": j.get("conclusion"),
                "html_url": j.get("html_url"),
            }
        )
    return {"jobs": jobs}


@mcp_tool(write_action=False)
async def get_job_logs(
    full_name: str,
    job_id: int,
) -> Dict[str, Any]:
    client = _github_client_instance()
    url = f"/repos/{full_name}/actions/jobs/{job_id}/logs"
    resp = await client.get(url, follow_redirects=True)
    text = resp.text
    if len(text) > 16000:
        text = text[:16000] + "\n...[truncated logs]"
    return {"status": resp.status_code, "text": text}


@mcp_tool(write_action=False)
async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    start = time.time()
    while True:
        info = await get_workflow_run(full_name, run_id)
        status = info.get("status")
        if status in ("completed", "cancelled", "failure", "success"):
            return info
        if time.time() - start > timeout_seconds:
            raise GitHubAPIError(f"Workflow run {run_id} did not complete within {timeout_seconds}s")
        await asyncio.sleep(poll_interval_seconds)


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
    params = {"state": state, "per_page": per_page, "page": page}
    if head:
        params["head"] = head
    if base:
        params["base"] = base
    resp = await _github_request("GET", f"/repos/{full_name}/pulls", params=params)
    prs = resp["json"]
    trimmed = []
    for pr in prs:
        trimmed.append(
            {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "head": pr.get("head", {}).get("ref"),
                "base": pr.get("base", {}).get("ref"),
                "html_url": pr.get("html_url"),
            }
        )
    return {"pull_requests": trimmed}


@mcp_tool(write_action=True)
async def merge_pull_request(
    full_name: str,
    number: int,
    merge_method: str = "squash",
    commit_title: Optional[str] = None,
    commit_message: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"merge PR #{number}")
    body: Dict[str, Any] = {"merge_method": merge_method}
    if commit_title:
        body["commit_title"] = commit_title
    if commit_message:
        body["commit_message"] = commit_message
    resp = await _github_request("PUT", f"/repos/{full_name}/pulls/{number}/merge", json_body=body)
    return {"merged": resp["json"].get("merged", False), "sha": resp["json"].get("sha")}


@mcp_tool(write_action=True)
async def close_pull_request(
    full_name: str,
    number: int,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"close PR #{number}")
    body = {"state": "closed"}
    resp = await _github_request("PATCH", f"/repos/{full_name}/pulls/{number}", json_body=body)
    return {"state": resp["json"].get("state")}


@mcp_tool(write_action=True)
async def comment_on_pull_request(
    full_name: str,
    number: int,
    body: str,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"comment on PR #{number}")
    resp = await _github_request(
        "POST",
        f"/repos/{full_name}/issues/{number}/comments",
        json_body={"body": body},
    )
    return {"id": resp["json"].get("id"), "html_url": resp["json"].get("html_url")}


@mcp_tool(write_action=False)
async def compare_refs(
    full_name: str,
    base: str,
    head: str,
) -> Dict[str, Any]:
    resp = await _github_request("GET", f"/repos/{full_name}/compare/{base}...{head}")
    data = resp["json"]
    files = data.get("files", [])
    trimmed_files = []
    for f in files[:100]:
        patch = f.get("patch")
        if patch:
            patch = _trim(patch, 8000)
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
        "ahead_by": data.get("ahead_by"),
        "behind_by": data.get("behind_by"),
        "total_commits": data.get("total_commits"),
        "files": trimmed_files,
    }


@mcp_tool(write_action=True)
async def trigger_and_wait_for_workflow(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"trigger workflow {workflow}")
    await _github_request(
        "POST",
        f"/repos/{full_name}/actions/workflows/{workflow}/dispatches",
        json_body={"ref": ref, **({"inputs": inputs} if inputs else {})},
    )
    start = time.time()
    run_id = None
    while time.time() - start < timeout_seconds:
        list_resp = await _github_request(
            "GET",
            f"/repos/{full_name}/actions/runs",
            params={"branch": ref, "event": "workflow_dispatch", "per_page": 5},
        )
        runs = list_resp["json"].get("workflow_runs", [])
        if runs:
            run_id = runs[0].get("id")
            break
        await asyncio.sleep(poll_interval_seconds)
    if run_id is None:
        raise GitHubAPIError(f"Workflow {workflow} did not start within {timeout_seconds}s")
    result = await wait_for_workflow_run(
        full_name=full_name,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    return {"run_id": run_id, "conclusion": result.get("conclusion"), "html_url": result.get("html_url")}


# --------------------------------------------------------------------
# Branch /
