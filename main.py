import os
import asyncio
import base64
import tempfile
import shutil
import subprocess
import textwrap
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastmcp import FastMCP, tool
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.routing import Route


# ------------------------------------------------------------------------------
# Configuration and globals
# ------------------------------------------------------------------------------

GITHUB_PAT = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_PAT:
    raise RuntimeError("GITHUB_PAT or GITHUB_TOKEN must be set")

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")

HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", 150))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", 300))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", 200))

MAX_CONCURRENCY = int(os.environ.get("MAX_CONCURRENCY", 80))
FETCH_FILES_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", MAX_CONCURRENCY))

TOOL_STDOUT_MAX_CHARS = 12000
LOGS_MAX_CHARS = 16000

GIT_AUTHOR_NAME = os.environ.get("GIT_AUTHOR_NAME", "Ally")
GIT_AUTHOR_EMAIL = os.environ.get("GIT_AUTHOR_EMAIL", "ally@example.com")
GIT_COMMITTER_NAME = os.environ.get("GIT_COMMITTER_NAME", GIT_AUTHOR_NAME)
GIT_COMMITTER_EMAIL = os.environ.get("GIT_COMMITTER_EMAIL", GIT_AUTHOR_EMAIL)

WRITE_ALLOWED = os.environ.get("GITHUB_MCP_AUTO_APPROVE", "0") == "1"

_http_client_github: Optional[httpx.AsyncClient] = None
_http_client_external: Optional[httpx.AsyncClient] = None
_concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

mcp = FastMCP("GitHub Fast MCP", json_response=True)


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


def _github_client_instance() -> httpx.AsyncClient:
    global _http_client_github
    if _http_client_github is None:
        _http_client_github = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers={
                "Authorization": f"Bearer {GITHUB_PAT}",
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
) -> Dict[str, Any]:
    client = _github_client_instance()
    async with _concurrency_semaphore:
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
    try:
        return {"status_code": resp.status_code, "json": resp.json()}
    except Exception:
        return {"status_code": resp.status_code, "json": None}


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

    stdout = stdout_bytes.decode("utf-8", errors="replace")[:TOOL_STDOUT_MAX_CHARS]
    stderr = stderr_bytes.decode("utf-8", errors="replace")[:TOOL_STDOUT_MAX_CHARS]

    return {
        "exit_code": proc.returncode,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
    }


async def _clone_repo(full_name: str, ref: str = "main") -> str:
    tmpdir = tempfile.mkdtemp(prefix="mcp-github-")
    token = GITHUB_PAT
    if not token:
        raise GitHubAuthError("Missing GitHub token for cloning")

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


# ------------------------------------------------------------------------------
# Write gating and mcp_tool decorator
# ------------------------------------------------------------------------------


def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    global WRITE_ALLOWED
    WRITE_ALLOWED = bool(approved)
    return {"write_allowed": WRITE_ALLOWED}


def _ensure_write_allowed(context: str) -> None:
    if not WRITE_ALLOWED:
        raise WriteNotAuthorizedError(
            f"MCP write action is temporarily disabled (context: {context})"
        )


def mcp_tool(*, write_action: bool = False, **kwargs):
    def decorator(func):
        decorated = tool(**kwargs)(func)
        setattr(decorated, "write_action", write_action)
        return decorated

    return decorator


# ------------------------------------------------------------------------------
# Read-only tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=False)
def get_rate_limit() -> Dict[str, Any]:
    return asyncio.run(_github_request("GET", "/rate_limit"))


@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> Dict[str, Any]:
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    return await _github_request("GET", f"/repos/{full_name}")


@mcp_tool(write_action=False)
async def list_branches(
    full_name: str,
    per_page: int = 100,
    page: int = 1,
) -> Dict[str, Any]:
    params = {"per_page": per_page, "page": page}
    return await _github_request("GET", f"/repos/{full_name}/branches", params=params)


@mcp_tool(write_action=False)
async def get_file_contents(
    full_name: str,
    path: str,
    ref: str = "main",
) -> Dict[str, Any]:
    return await _decode_github_content(full_name, path, ref)


@mcp_tool(write_action=False)
async def fetch_files(
    full_name: str,
    paths: List[str],
    ref: str = "main",
) -> Dict[str, Any]:
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
async def graphql_query(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = _github_client_instance()
    payload = {"query": query, "variables": variables or {}}
    async with _concurrency_semaphore:
        resp = await client.post("/graphql", json=payload)

    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub GraphQL error {resp.status_code}: {resp.text}"
        )
    return resp.json()


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    client = _external_client_instance()
    async with _concurrency_semaphore:
        resp = await client.get(url)
    return {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "content": resp.text[:TOOL_STDOUT_MAX_CHARS],
    }


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
async def get_workflow_run(full_name: str, run_id: int) -> Dict[str, Any]:
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
    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET",
        f"/repos/{full_name}/actions/runs/{run_id}/jobs",
        params=params,
    )


@mcp_tool(write_action=False)
async def get_job_logs(full_name: str, job_id: int) -> Dict[str, Any]:
    client = _github_client_instance()
    async with _concurrency_semaphore:
        resp = await client.get(
            f"/repos/{full_name}/actions/jobs/{job_id}/logs",
            headers={"Accept": "application/vnd.github+json"},
        )
    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub job logs error {resp.status_code}: {resp.text}"
        )
    text = resp.text[:LOGS_MAX_CHARS]
    return {"status_code": resp.status_code, "logs": text}


@mcp_tool(write_action=False)
async def wait_for_workflow_run(
    full_name: str,
    run_id: int,
    timeout_seconds: int = 900,
    poll_interval_seconds: int = 10,
) -> Dict[str, Any]:
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
# Branch / commit / PR tools
# ------------------------------------------------------------------------------


@mcp_tool(write_action=True)
async def create_branch(
    full_name: str,
    new_branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
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
        if not (content_url.startswith("http://") or content_url.startswith("https://")):
            raise GitHubAPIError(
                "commit_file_async content_url must be an absolute http(s) URL. "
                "In ChatGPT, pass the sandbox file path (e.g. sandbox:/mnt/data/file) "
                "and the host will rewrite it to a real URL before it reaches this server.",
            )
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
    _ensure_write_allowed(f"create PR from {head} to {base} in {full_name}")
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
    return resp


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
    _ensure_write_allowed(f"update_files_and_open_pr {full_name} {title}")

    branch = new_branch or f"ally-{os.urandom(4).hex()}"
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
            if not (content_url.startswith("http://") or content_url.startswith("https://")):
                raise GitHubAPIError(
                    "update_files_and_open_pr content_url must be an absolute http(s) URL. "
                    "In ChatGPT, pass the sandbox file path (e.g. sandbox:/mnt/data/file) "
                    "and the host will rewrite it to a real URL before it reaches this server.",
                )
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
) -> Dict[str, Any]:
    _ensure_write_allowed(f"run_command {command} in {full_name}@{ref}")
    repo_dir = await _clone_repo(full_name, ref=ref)
    try:
        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)
        result = await _run_shell(command, cwd=cwd, timeout_seconds=timeout_seconds)
        return {
            "repo_dir": repo_dir,
            "workdir": workdir,
            "result": result,
        }
    finally:
        _cleanup_dir(repo_dir)


@mcp_tool(write_action=True)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
) -> Dict[str, Any]:
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
    _ensure_write_allowed(f"apply_patch_and_open_pr on {full_name}@{base_branch}")

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

        commit_result = await _run_shell(
            f'git commit -am "{title}"',
            cwd=repo_dir,
            timeout_seconds=60,
        )
        if commit_result["exit_code"] != 0:
            error = "git_commit_failed"
            error_stderr = commit_result.get("stderr", "")
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

        token = GITHUB_PAT
        if not token:
            raise GitHubAuthError("Missing GitHub token for push")

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
# Starlette app and routes
# ------------------------------------------------------------------------------


async def homepage(request):
    return PlainTextResponse("GitHub MCP server is running\n")


async def healthz(request):
    return PlainTextResponse("OK\n")


async def _sse_endpoint(request):
    return await mcp.asgi_sse(request)


routes = [
    Route("/", homepage),
    Route("/healthz", healthz),
    Route("/sse", _sse_endpoint, methods=["GET", "POST", "OPTIONS"]),
]

app = Starlette(routes=routes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
