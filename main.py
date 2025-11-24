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
        setattr(tool, "write_action", write_action)
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
# PR / issue management tools (new)
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
    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(body_bytes).decode("ascii"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    try:
        result = await _github_request(
            "PUT",
            f"/repos/{full_name.strip()}/contents/{path.lstrip('/')}",
            json_body=payload,
        )
    except Exception as e:
        print(f"[commit] failed for {full_name}/{path}: {e}")
        raise
    raw_json = result.get("json", {}) or {}
    content_info = raw_json.get("content") or {}
    commit_info = raw_json.get("commit") or {}
    return {
        "status": result.get("status"),
        "path": path,
        "branch": branch,
        "content": {
            "path": content_info.get("path"),
            "sha": content_info.get("sha"),
            "html_url": content_info.get("html_url"),
        },
        "commit": {
            "sha": commit_info.get("sha"),
            "url": commit_info.get("url"),
            "html_url": commit_info.get("html_url"),
            "message": commit_info.get("message"),
        },
    }


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
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")

    _ensure_write_allowed(f"commit file async {path}")

    print(
        "[commit_file_async] scheduling full_name=%r path=%r branch=%r message=%r "
        "has_content=%s content_url=%r sha=%r"
        % (full_name, path, branch, message, content is not None, content_url, sha)
    )

    if content is None and content_url is None:
        raise ValueError("Either content or content_url must be provided")
    if content is not None and content_url is not None:
        raise ValueError("Provide content or content_url, but not both")

    if content_url is not None:
        if not isinstance(content_url, str) or not content_url.strip():
            raise ValueError("content_url must be a non-empty string when provided")
        client = _external_client_instance()
        response = await client.get(content_url)
        if response.status_code >= 400:
            raise GitHubAPIError(
                f"Failed to fetch content from {content_url}: {response.status_code}"
            )
        body_bytes = response.content
    else:
        body_bytes = content.encode("utf-8")

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
    _ensure_write_allowed(f"create PR {title}")
    payload = {
        "title": title,
        "head": head,
        "base": base,
        "body": body or "",
        "draft": draft,
    }
    resp = await _github_request("POST", f"/repos/{full_name}/pulls", json_body=payload)
    j = resp["json"]
    return {
        "number": j.get("number"),
        "state": j.get("state"),
        "html_url": j.get("html_url"),
        "title": j.get("title"),
    }


@mcp_tool(write_action=True)
async def trigger_workflow_dispatch(
    full_name: str,
    workflow: str,
    ref: str,
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"trigger workflow_dispatch {workflow}")
    payload: Dict[str, Any] = {"ref": ref}
    if inputs:
        payload["inputs"] = inputs
    await _github_request(
        "POST",
        f"/repos/{full_name}/actions/workflows/{workflow}/dispatches",
        json_body=payload,
    )
    return {"triggered": True}


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
    _ensure_write_allowed(f"update_files_and_open_pr {title}")
    branch = new_branch or f"ally-{base_branch}-{secrets.token_hex(4)}"
    await ensure_branch(full_name, branch, from_ref=base_branch)

    for f in files:
        path = f["path"]
        file_message = f.get("message") or title
        content = f.get("content")
        content_url = f.get("content_url")
        if content is None and content_url is None:
            raise ValueError(f"File entry for {path} must have content or content_url")

        if content_url is not None:
            if not isinstance(content_url, str) or not content_url.strip():
                raise ValueError("content_url must be a non-empty string when provided")
            client = _external_client_instance()
            response = await client.get(content_url)
            if response.status_code >= 400:
                raise GitHubAPIError(
                    f"Failed to fetch content from {content_url}: {response.status_code}"
                )
            body_bytes = response.content
        else:
            body_bytes = content.encode("utf-8")

        sha = await _resolve_file_sha(full_name, path, branch)
        await _perform_github_commit(
            full_name=full_name,
            path=path,
            message=file_message,
            body_bytes=body_bytes,
            branch=branch,
            sha=sha,
        )

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

@mcp_tool(write_action=False)
async def run_command(
    full_name: str,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"run_command on {full_name}@{ref}")
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
    draft: bool = False,
) -> Dict[str, Any]:
    _ensure_write_allowed(f"apply_patch_and_open_pr on {full_name}:{base_branch}")
    branch = new_branch or f"ally-patch-{secrets.token_hex(4)}"
    repo_dir = await _clone_repo(full_name, base_branch)
    try:
        await _run_shell(f"git checkout -b {branch}", cwd=repo_dir, timeout_seconds=60)
        patch_file = os.path.join(repo_dir, "mcp_patch.diff")
        with open(patch_file, "w", encoding="utf-8") as f:
            f.write(patch)
        result = await _run_shell(
            f"git apply --whitespace=nowarn {patch_file}", cwd=repo_dir, timeout_seconds=60
        )
        if result["exit_code"] != 0:
            raise GitHubAPIError(f"git apply failed: {result['stderr']}")

        await _run_shell(
            'git commit -am "{}"'.format(title.replace('"', '\\"')),
            cwd=repo_dir,
            timeout_seconds=60,
        )

        tests_result = None
        if run_tests_flag:
            tests_result = await run_tests(
                full_name=full_name, ref=branch, test_command=test_command
            )
            if tests_result["exit_code"] != 0 or tests_result["timed_out"]:
                return {"branch": branch, "tests": tests_result, "pull_request": None}

        push_url = _make_clone_url(full_name)
        await _run_shell(
            f"git push {push_url} {branch}", cwd=repo_dir, timeout_seconds=120
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
# ASGI / Starlette
# --------------------------------------------------------------------

async def _sse_endpoint(request: Request) -> Response:
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
