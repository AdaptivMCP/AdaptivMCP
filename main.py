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
from starlette.routing import Route, Mount
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# MCP framework & tool decorator
from fastmcp import FastMCP, mcp_tool  # assume this is your existing import

# Custom errors
class GitHubAuthError(Exception):
    pass

class GitHubAPIError(Exception):
    pass

# Constants
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise GitHubAuthError("GITHUB_PAT or GITHUB_TOKEN environment variable must be set")

# HTTPX client pools (shared)
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

# MCP server definition
mcp = FastMCP("GitHub Fast MCP", json_response=True)
WRITE_ALLOWED = False

@mcp_tool(write_action=False)
async def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    global WRITE_ALLOWED
    WRITE_ALLOWED = bool(approved)
    return {"write_actions_enabled": WRITE_ALLOWED}

def _ensure_write_allowed(context: str):
    if not WRITE_ALLOWED:
        raise GitHubAPIError(f"Write tools are not authorized for this session (context: {context})")

# Helper for GitHub REST requests
async def _github_request(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = _github_client_instance()
    response = await client.request(method, path if path.startswith("http") else f"{GITHUB_API_BASE}{path}", json=json_body, params=params)
    if response.status_code == 401:
        raise GitHubAuthError("GitHub authentication failed: 401")
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub API error {response.status_code}: {response.text}")
    data = response.json()
    return {"status": response.status_code, "json": data}

# Helper for GraphQL
async def _github_graphql(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client = _github_client_instance()
    response = await client.post("/graphql", json={"query": query, "variables": variables or {}})
    if response.status_code == 401:
        raise GitHubAuthError("GitHub authentication failed: 401 (graphql)")
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub GraphQL error {response.status_code}: {response.text}")
    return response.json()

# Helper to decode GitHub content (handled by your code previously)
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
            "text": text,
            "sha": j.get("sha"),
            "path": j.get("path"),
            "html_url": j.get("html_url"),
        }
    elif resp.status_code in (404, 410):
        return {"text": None, "sha": None, "path": path, "html_url": None}
    else:
        raise GitHubAPIError(f"Failed to fetch content: {resp.status_code}, body={resp.text}")

# --- New Workspace & patch helpers ---

MAX_STDOUT = int(os.environ.get("TOOL_STDOUT_MAX_CHARS", "12000"))

async def _run_shell(
    cmd: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Runs a shell command, returns truncated stdout/stderr, exit code, timed out flag.
    """
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
    # embed token safely
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

# Helper to trim content
def _trim(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + "\n...[truncated]"

# --- New GitHub‑based helpers for enhanced tools ---

# List PRs
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
        trimmed.append({
            "number": pr.get("number"),
            "title": pr.get("title"),
            "state": pr.get("state"),
            "head": pr.get("head", {}).get("ref"),
            "base": pr.get("base", {}).get("ref"),
            "html_url": pr.get("html_url"),
        })
    return {"pull_requests": trimmed}

# Merge PR
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

# Close PR without merge
@mcp_tool(write_action=True)
async def close_pull_request(
    full_name: str,
    number: int,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"close PR #{number}")
    body = {"state": "closed"}
    resp = await _github_request("PATCH", f"/repos/{full_name}/pulls/{number}", json_body=body)
    return {"state": resp["json"].get("state")}

# Comment on PR
@mcp_tool(write_action=True)
async def comment_on_pull_request(
    full_name: str,
    number: int,
    body: str,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"comment on PR #{number}")
    resp = await _github_request("POST", f"/repos/{full_name}/issues/{number}/comments", json_body={"body": body})
    return {"id": resp["json"].get("id"), "html_url": resp["json"].get("html_url")}

# Compare two refs
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
    for f in files[:100]:  # limit number of files
        patch = f.get("patch")
        if patch:
            patch = _trim(patch, 8000)
        trimmed_files.append({
            "filename": f.get("filename"),
            "status": f.get("status"),
            "additions": f.get("additions"),
            "deletions": f.get("deletions"),
            "changes": f.get("changes"),
            "patch": patch,
        })
    return {
        "ahead_by": data.get("ahead_by"),
        "behind_by": data.get("behind_by"),
        "total_commits": data.get("total_commits"),
        "files": trimmed_files,
    }

# Trigger workflow and wait for completion
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
    # Trigger
    await _github_request("POST", f"/repos/{full_name}/actions/workflows/{workflow}/dispatches",
                           json_body={"ref": ref, **({"inputs": inputs} if inputs else {})})
    # Poll for a new run
    start = time.time()
    run_id = None
    while time.time() - start < timeout_seconds:
        list_resp = await _github_request("GET", f"/repos/{full_name}/actions/runs",
                                          params={"branch": ref, "event": "workflow_dispatch", "per_page": 5})
        runs = list_resp["json"].get("workflow_runs", [])
        if runs:
            # take the most recent
            run_id = runs[0].get("id")
            break
        await asyncio.sleep(poll_interval_seconds)
    if run_id is None:
        raise GitHubAPIError(f"Workflow {workflow} did not start within {timeout_seconds}s")

    # Wait for it to complete
    result = await wait_for_workflow_run(full_name=full_name, run_id=run_id, timeout_seconds=timeout_seconds, poll_interval_seconds=poll_interval_seconds)
    return {"run_id": run_id, "conclusion": result.get("conclusion"), "html_url": result.get("html_url")}

# Workspace tools
@mcp_tool(write_action=False)
async def run_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"run_command on {full_name}@{ref}")  # optional write guard
    repo_dir = await _clone_repo(full_name, ref)
    cwd = repo_dir
    if workdir:
        cwd = os.path.join(repo_dir, workdir)
    try:
        result = await _run_shell(command, cwd=cwd, timeout_seconds=timeout_seconds)
    finally:
        await _cleanup_dir(repo_dir)
    return result

@mcp_tool(write_action=False)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"run_tests on {full_name}@{ref}")
    return await run_command(full_name=full_name, ref=ref, command=test_command, timeout_seconds=timeout_seconds, workdir=workdir)

# Apply unified diff patch and open a PR
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
    draft: bool = False,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"apply_patch_and_open_pr on {full_name}:{base_branch}")
    branch = new_branch or f"ally-patch-{secrets.token_hex(4)}"
    repo_dir = await _clone_repo(full_name, base_branch)
    try:
        # Create branch
        await _run_shell(f"git checkout -b {branch}", cwd=repo_dir, timeout_seconds=60)
        # Apply patch
        patch_file = os.path.join(repo_dir, "mcp_patch.diff")
        with open(patch_file, "w", encoding="utf-8") as f:
            f.write(patch)
        result = await _run_shell(f"git apply --whitespace=nowarn {patch_file}", cwd=repo_dir, timeout_seconds=60)
        if result["exit_code"] != 0:
            raise GitHubAPIError(f"git apply failed: {result['stderr']}")

        # Commit changes
        await _run_shell('git commit -am "{}"'.format(title.replace('"', '\\"')), cwd=repo_dir, timeout_seconds=60)

        # Optionally run tests
        tests_result = None
        if run_tests_flag:
            tests_result = await run_tests(full_name=full_name, ref=branch, test_command=test_command)
            if tests_result["exit_code"] != 0 or tests_result["timed_out"]:
                # abort before push
                return {"branch": branch, "tests": tests_result, "pull_request": None}

        # Push branch
        push_url = _make_clone_url(full_name)
        await _run_shell(f"git push {push_url} {branch}", cwd=repo_dir, timeout_seconds=120)

        # Create PR
        pr_resp = await _github_request("POST", f"/repos/{full_name}/pulls",
                                        json_body={
                                            "title": title,
                                            "head": branch,
                                            "base": base_branch,
                                            "body": body or ""
                                        })
        pr_json = pr_resp["json"]
        return {"branch": branch, "tests": tests_result, "pull_request": {
            "number": pr_json.get("number"),
            "html_url": pr_json.get("html_url"),
            "state": pr_json.get("state"),
            "title": pr_json.get("title")
        }}
    finally:
        await _cleanup_dir(repo_dir)

# --- Your existing tools (read + write) kept intact ---

# (Insert all your previously defined tools here: get_rate_limit, get_repository, list_branches, get_file_contents, fetch_files, graphql_query, fetch_url, list_workflow_runs, get_workflow_run, list_workflow_run_jobs, get_job_logs, wait_for_workflow_run, create_branch, ensure_branch, commit_file_async, create_pull_request, trigger_workflow_dispatch, update_files_and_open_pr)

# Note: For brevity I am not repeating them here, assuming they remain unchanged.

# --- ASGI application setup ---

async def _sse_endpoint(request: Request) -> Response:
    # This is your existing SSE endpoint logic
    return await mcp.asgi_sse(request)

async def _healthz(request: Request) -> Response:
    return PlainTextResponse("OK")

async def _root(request: Request) -> Response:
    return PlainTextResponse("GitHub MCP server is running")

routes = [
    Route("/", _root),
    Route("/healthz", _healthz),
    Route("/sse", _sse_endpoint, methods=["GET", "POST", "OPTIONS"]),
]

app = Starlette(debug=False, routes=routes)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

@app.on_event("shutdown")
async def shutdown_event():
    await _close_clients()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")
