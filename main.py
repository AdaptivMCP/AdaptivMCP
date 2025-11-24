"""
GitHub Fast MCP server for private repositories.

This server exposes read and write utilities for GitHub repositories while
preserving write/read intent metadata through a compatibility-aware decorator.
"""
from __future__ import annotations

import asyncio
import base64
import os
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.routing import Mount

# ============================================================
# Configuration
# ============================================================
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise RuntimeError(
        "GITHUB_PAT or GITHUB_TOKEN environment variable must be set for private repo access."
    )

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_GRAPHQL_URL = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")

HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", "300"))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "256"))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "512"))
HTTPX_HTTP2 = os.environ.get("HTTPX_HTTP2", "0") != "0"

DEFAULT_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", "100"))

# ============================================================
# Errors
# ============================================================


class GitHubAuthError(RuntimeError):
    """Missing GitHub credentials or invalid token."""


class GitHubAPIError(RuntimeError):
    """GitHub API call failed."""


# ============================================================
# MCP server setup
# ============================================================
mcp = FastMCP("GitHub Fast MCP (private repos)", json_response=True)
WRITE_ACTIONS_APPROVED: bool = os.environ.get("GITHUB_MCP_AUTO_APPROVE", "0") != "0"


def mcp_tool(*, write_action: bool = False, **kwargs):
    """
    Compatibility wrapper for ``@mcp.tool`` that keeps write/read intent metadata.

    Older FastMCP releases reject unknown keyword arguments. This decorator stores
    the ``write_action`` flag on the original function, the tool returned by
    FastMCP, and the exported wrapper so clients can still introspect intent.
    """

    def decorator(func):
        tool = mcp.tool(**kwargs)(func)

        @wraps(func)
        async def wrapper(*args, **inner_kwargs):
            return await tool(*args, **inner_kwargs)

        for obj in (func, tool, wrapper):
            setattr(obj, "write_action", write_action)
        return wrapper

    return decorator


# ============================================================
# Shared clients
# ============================================================
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
        if "http2" in str(exc):
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


def _ensure_github_client() -> httpx.AsyncClient:
    global _github_client
    if _github_client is None:
        _github_client = _build_client(GITHUB_API_BASE)
    return _github_client


def _ensure_external_client() -> httpx.AsyncClient:
    global _external_client
    if _external_client is None:
        _external_client = _build_client()
    return _external_client


async def _close_clients() -> None:
    global _github_client, _external_client
    try:
        if _github_client is not None:
            await _github_client.aclose()
    finally:
        _github_client = None
    try:
        if _external_client is not None:
            await _external_client.aclose()
    finally:
        _external_client = None


# ============================================================
# Auth helpers
# ============================================================
async def _ensure_write_allowed(action: str) -> None:
    if not WRITE_ACTIONS_APPROVED:
        raise GitHubAuthError(
            "Write operations (commit files, create branches, open PRs) need to be "
            "authorized for this session. Call authorize_github_session or "
            "authorize_write_actions once to proceed."
        )


# ============================================================
# HTTP helpers
# ============================================================
async def _github_request(
    method: str,
    path_or_url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    full_url: bool = False,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    client = _ensure_github_client()
    url = path_or_url if full_url or path_or_url.startswith("http") else path_or_url
    response = await client.request(
        method.upper(),
        url,
        params=params,
        json=json_body,
        headers=headers or {},
        timeout=httpx.Timeout(timeout) if timeout else None,
    )

    result: Dict[str, Any] = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
        "bytes": response.content,
    }
    try:
        result["text"] = response.text
    except Exception:
        result["text"] = None

    if "application/json" in response.headers.get("content-type", "").lower():
        try:
            result["json"] = response.json()
        except Exception:
            pass

    if response.status_code >= 400:
        body_sample = (
            result.get("text")
            or (result.get("bytes") and result["bytes"][:1000])
            or b""
        )
        raise GitHubAPIError(
            f"GitHub API error {response.status_code} for {method} {url}: "
            f"{str(body_sample)[:1000]}"
        )
    return result


async def _external_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Union[str, bytes, Dict[str, Any]]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    client = _ensure_external_client()
    request_kwargs: Dict[str, Any] = {}
    if headers:
        request_kwargs["headers"] = headers
    if isinstance(body, (str, bytes)):
        request_kwargs["content"] = body
    elif body is not None:
        request_kwargs["json"] = body

    response = await client.request(
        method.upper(),
        url,
        timeout=httpx.Timeout(timeout) if timeout else None,
        **request_kwargs,
    )

    result: Dict[str, Any] = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
        "bytes": response.content,
    }
    try:
        result["text"] = response.text
    except Exception:
        result["text"] = None

    if "application/json" in response.headers.get("content-type", "").lower():
        try:
            result["json"] = response.json()
        except Exception:
            pass

    if response.status_code >= 400:
        body_sample = (
            result.get("text")
            or (result.get("bytes") and result["bytes"][:1000])
            or b""
        )
        raise RuntimeError(
            f"HTTP error {response.status_code} when fetching {url}: "
            f"{str(body_sample)[:1000]}"
        )
    return result


# ============================================================
# MCP tools - auth
# ============================================================
@mcp_tool(write_action=False)
async def authorize_github_session() -> str:
    """Approve GitHub MCP write actions for the current session."""

    global WRITE_ACTIONS_APPROVED
    WRITE_ACTIONS_APPROVED = True
    return (
        "GitHub MCP write actions authorized for this session. You can now commit files, "
        "create branches, and open PRs without extra prompts."
    )


@mcp_tool(write_action=False)
async def authorize_write_actions() -> str:
    """Alias for authorize_github_session for clarity."""

    return await authorize_github_session()


# ============================================================
# MCP tools - low level GitHub access
# ============================================================
@mcp_tool(write_action=True)
async def github_request(
    method: str,
    path: str,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Any] = None,
) -> Dict[str, Any]:
    method_upper = method.upper()
    if method_upper not in {"GET", "HEAD", "OPTIONS"}:
        await _ensure_write_allowed(f"{method_upper} {path}")
    return await _github_request(method_upper, path, params=query, json_body=body)


@mcp_tool(write_action=True)
async def github_graphql(
    query: str, variables: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    await _ensure_write_allowed("GraphQL request")
    client = _ensure_github_client()
    payload = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    response = await client.post(GITHUB_GRAPHQL_URL, json=payload)
    if response.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub GraphQL error {response.status_code}: {response.text[:1000]}"
        )
    try:
        return {
            "status": response.status_code,
            "url": str(response.url),
            "json": response.json(),
            "text": response.text,
        }
    except Exception:
        return {"status": response.status_code, "url": str(response.url), "text": response.text}


@mcp_tool(write_action=False)
async def fetch_url(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Union[str, bytes, Dict[str, Any]]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Fetch an arbitrary URL on the web (follows redirects)."""

    return await _external_fetch(url, method=method, headers=headers, body=body, timeout=timeout)


@mcp_tool(write_action=False)
async def sanity_check(ctx: Context[ServerSession, None]) -> str:
    """Simple tool to validate MCP server wiring."""

    await ctx.debug("sanity_check tool was called successfully.")
    return "GitHub Fast MCP server is up and responding."


# ============================================================
# MCP tools - GitHub introspection
# ============================================================
@mcp_tool(write_action=False)
async def github_rate_limit() -> Dict[str, Any]:
    return await _github_request("GET", "/rate_limit")


@mcp_tool(write_action=False)
async def github_whoami() -> Dict[str, Any]:
    return await _github_request("GET", "/user")


@mcp_tool(write_action=False)
async def list_repo_tree(
    repository_full_name: str,
    ref: str = "main",
    recursive: bool = True,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    endpoint = f"/repos/{repository_full_name.strip()}/git/trees/{ref}"
    params = {"recursive": 1} if recursive else None
    result = await _github_request("GET", endpoint, params=params)
    return {"status": result["status"], "url": result["url"], "tree": result.get("json")}


@mcp_tool(write_action=False)
async def list_repo_files(
    repository_full_name: str,
    ref: str = "main",
) -> Dict[str, Any]:
    tree_result = await list_repo_tree(repository_full_name, ref=ref, recursive=True)
    tree = tree_result.get("tree") or {}
    entries = tree.get("tree") or []
    files = [entry["path"] for entry in entries if entry.get("type") == "blob"]
    return {
        "status": tree_result.get("status", 200),
        "url": tree_result.get("url"),
        "file_count": len(files),
        "files": files,
    }


@mcp_tool(write_action=False)
async def search_code(
    repository_full_name: str,
    query: str,
    per_page: int = 50,
    page: int = 1,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    search_query = f"{query} repo:{repository_full_name}"
    params = {"q": search_query, "per_page": max(1, min(per_page, 100)), "page": max(1, page)}
    result = await _github_request("GET", "/search/code", params=params)
    return {
        "status": result["status"],
        "url": result["url"],
        "search_query": search_query,
        "results": result.get("json"),
    }


# ============================================================
# MCP tools - file fetch helpers
# ============================================================
async def _decode_contents_item(item: Dict[str, Any], encoding: str = "utf-8") -> Dict[str, Any]:
    if not item:
        raise GitHubAPIError("Empty contents item.")
    item_type = item.get("type")
    if item_type == "dir":
        return {"type": "dir", "entries": item}
    if item_type == "file":
        if item.get("encoding") == "base64":
            raw = base64.b64decode(item.get("content", ""))
            try:
                return {"type": "file", "text": raw.decode(encoding), "size": len(raw)}
            except Exception:
                return {"type": "file", "bytes": raw, "size": len(raw)}
        content = item.get("content", "")
        return {"type": "file", "text": content, "size": len(content)}
    return {"type": item_type or "unknown", "json": item}


@mcp_tool(write_action=False)
async def fetch_file(
    repository_full_name: str,
    path: str,
    ref: str = "main",
    encoding: str = "utf-8",
    raw: bool = True,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")

    owner_repo = repository_full_name.strip()
    endpoint = f"/repos/{owner_repo}/contents/{path}"
    params = {"ref": ref}

    if raw:
        headers = {"Accept": "application/vnd.github.v3.raw"}
        result = await _github_request(
            "GET", endpoint, params=params, headers=headers, full_url=False, timeout=timeout
        )
        return {
            "status": result["status"],
            "url": result["url"],
            "text": result.get("text"),
            "bytes": result.get("bytes"),
        }

    result = await _github_request(
        "GET", endpoint, params=params, headers=None, full_url=False, timeout=timeout
    )
    item = result.get("json")
    if item is None:
        raise GitHubAPIError(
            f"Unexpected response when fetching file: {result.get('text') or result.get('bytes')}"
        )
    decoded = await _decode_contents_item(item, encoding=encoding)
    return {"status": result["status"], "url": result["url"], "decoded": decoded}


@mcp_tool(write_action=False)
async def fetch_files(
    repository_full_name: str,
    paths: List[str],
    ref: str = "main",
    encoding: str = "utf-8",
    raw: bool = True,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if not isinstance(paths, list):
        raise ValueError("paths must be a list of file paths.")
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def _fetch_one(p: str) -> Tuple[str, Dict[str, Any]]:
        async with semaphore:
            try:
                res = await fetch_file(
                    repository_full_name,
                    p,
                    ref=ref,
                    encoding=encoding,
                    raw=raw,
                    timeout=timeout,
                )
                return p, {"ok": True, "result": res}
            except Exception as exc:  # noqa: BLE001
                return p, {"ok": False, "error": str(exc)}

    results = dict(await asyncio.gather(*[_fetch_one(p) for p in paths]))
    successes = {k: v for k, v in results.items() if v.get("ok")}
    failures = {k: v for k, v in results.items() if not v.get("ok")}
    return {
        "count": len(paths),
        "succeeded": len(successes),
        "failed": len(failures),
        "results": results,
    }


# ============================================================
# MCP tools - write operations
# ============================================================
@mcp_tool(write_action=True)
async def commit_file(
    repository_full_name: str,
    path: str,
    content: str,
    message: str,
    branch: str = "main",
    encoding: str = "utf-8",
    sha: Optional[str] = None,
    committer_name: Optional[str] = None,
    committer_email: Optional[str] = None,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_write_allowed(f"commit {path}")

    owner_repo = repository_full_name.strip()
    endpoint = f"/repos/{owner_repo}/contents/{path}"
    target_branch = branch.strip() or "main"

    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode(encoding)).decode("utf-8"),
        "branch": target_branch,
    }
    if committer_name and committer_email:
        payload["committer"] = {"name": committer_name, "email": committer_email}

    file_sha = sha
    if file_sha is None:
        try:
            existing = await _github_request("GET", endpoint, params={"ref": target_branch})
            file_sha = (existing.get("json") or {}).get("sha")
        except GitHubAPIError:
            file_sha = None

    if file_sha:
        payload["sha"] = file_sha

    result = await _github_request("PUT", endpoint, json_body=payload)
    return {"status": result["status"], "url": result["url"], "result": result.get("json")}


async def _create_git_blob(
    repository_full_name: str,
    *,
    content: Union[str, bytes],
    encoding: str = "utf-8",
    use_base64: bool = True,
) -> str:
    owner_repo = repository_full_name.strip()
    payload: Dict[str, Any] = {"encoding": "base64" if use_base64 else "utf-8"}
    if isinstance(content, bytes):
        encoded = (
            base64.b64encode(content).decode("utf-8") if use_base64 else content.decode(encoding)
        )
    else:
        encoded = base64.b64encode(content.encode(encoding)).decode("utf-8") if use_base64 else content
    payload["content"] = encoded

    result = await _github_request("POST", f"/repos/{owner_repo}/git/blobs", json_body=payload)
    blob_sha = (result.get("json") or {}).get("sha")
    if not blob_sha:
        raise GitHubAPIError("Failed to create git blob")
    return blob_sha


async def _create_git_tree(
    repository_full_name: str,
    *,
    base_tree: str,
    entries: List[Dict[str, Any]],
) -> str:
    owner_repo = repository_full_name.strip()
    payload = {"base_tree": base_tree, "tree": entries}
    result = await _github_request("POST", f"/repos/{owner_repo}/git/trees", json_body=payload)
    tree_sha = (result.get("json") or {}).get("sha")
    if not tree_sha:
        raise GitHubAPIError("Failed to create git tree")
    return tree_sha


async def _create_git_commit(
    repository_full_name: str,
    *,
    message: str,
    tree_sha: str,
    parent_sha: str,
) -> str:
    owner_repo = repository_full_name.strip()
    payload = {"message": message, "tree": tree_sha, "parents": [parent_sha]}
    result = await _github_request("POST", f"/repos/{owner_repo}/git/commits", json_body=payload)
    commit_sha = (result.get("json") or {}).get("sha")
    if not commit_sha:
        raise GitHubAPIError("Failed to create git commit")
    return commit_sha


async def _update_branch_ref(
    repository_full_name: str,
    *,
    branch: str,
    sha: str,
    force: bool = False,
) -> Dict[str, Any]:
    owner_repo = repository_full_name.strip()
    endpoint = f"/repos/{owner_repo}/git/refs/heads/{branch}"
    return await _github_request("PATCH", endpoint, json_body={"sha": sha, "force": force})


async def _get_branch_sha(repository_full_name: str, branch: str) -> str:
    endpoint = f"/repos/{repository_full_name.strip()}/git/refs/heads/{branch}"
    result = await _github_request("GET", endpoint)
    sha = ((result.get("json") or {}).get("object") or {}).get("sha")
    if not sha:
        raise GitHubAPIError(f"Could not resolve branch '{branch}' for {repository_full_name}.")
    return sha


@mcp_tool(write_action=True)
async def commit_files_git(
    repository_full_name: str,
    files: List[Dict[str, Any]],
    message: str,
    branch: str = "main",
    encoding: str = "utf-8",
    force: bool = False,
    use_base64: bool = True,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    if not isinstance(files, list) or not files:
        raise ValueError("files must be a non-empty list of {path, content} items")

    await _ensure_write_allowed("commit multiple files")

    owner_repo = repository_full_name.strip()
    target_branch = branch.strip() or "main"

    head_sha = await _get_branch_sha(owner_repo, target_branch)
    commit_info = await _github_request("GET", f"/repos/{owner_repo}/git/commits/{head_sha}")
    base_tree_sha = ((commit_info.get("json") or {}).get("tree") or {}).get("sha")
    if not base_tree_sha:
        raise GitHubAPIError(
            f"Could not resolve base tree for branch '{target_branch}' in {owner_repo}."
        )

    tree_entries: List[Dict[str, Any]] = []
    created_blobs: List[Dict[str, str]] = []

    for item in files:
        if not isinstance(item, dict):
            raise ValueError("each file entry must be a dict with 'path' and 'content'")
        path = item.get("path")
        content = item.get("content")
        mode = item.get("mode", "100644")
        if not path or content is None:
            raise ValueError("each file entry must include path and content")

        blob_sha = await _create_git_blob(owner_repo, content=content, encoding=encoding, use_base64=use_base64)
        created_blobs.append({"path": path, "sha": blob_sha})
        tree_entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob_sha})

    new_tree_sha = await _create_git_tree(owner_repo, base_tree=base_tree_sha, entries=tree_entries)
    new_commit_sha = await _create_git_commit(
        owner_repo, message=message, tree_sha=new_tree_sha, parent_sha=head_sha
    )
    ref_update = await _update_branch_ref(owner_repo, branch=target_branch, sha=new_commit_sha, force=force)

    return {
        "status": ref_update.get("status", 200),
        "branch": target_branch,
        "commit_sha": new_commit_sha,
        "tree_sha": new_tree_sha,
        "blobs": created_blobs,
        "ref_update": ref_update.get("json"),
    }


@mcp_tool(write_action=True)
async def create_branch(
    repository_full_name: str,
    new_branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_write_allowed(f"create branch {new_branch}")

    base_sha = await _get_branch_sha(repository_full_name, from_ref)
    payload = {"ref": f"refs/heads/{new_branch}", "sha": base_sha}
    endpoint = f"/repos/{repository_full_name.strip()}/git/refs"
    result = await _github_request("POST", endpoint, json_body=payload)
    return {"status": result["status"], "url": result["url"], "result": result.get("json")}


@mcp_tool(write_action=True)
async def create_pull_request(
    repository_full_name: str,
    title: str,
    head: str,
    base: str = "main",
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_write_allowed(f"create PR from {head} to {base}")

    payload: Dict[str, Any] = {"title": title, "head": head, "base": base, "draft": draft}
    if body:
        payload["body"] = body

    endpoint = f"/repos/{repository_full_name.strip()}/pulls"
    result = await _github_request("POST", endpoint, json_body=payload)
    return {"status": result["status"], "url": result["url"], "pull_request": result.get("json")}


# ============================================================
# ASGI wiring
# ============================================================
app = Starlette(routes=[Mount("/", app=mcp.sse_app())])
app.add_event_handler("shutdown", lambda: asyncio.create_task(_close_clients()))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
# main.py
"""
GitHub Fast MCP server for private repositories.

This server exposes read and write utilities for GitHub repositories while
preserving write/read intent metadata through a compatibility-aware decorator.
"""
from __future__ import annotations

import asyncio
import base64
import os
from functools import wraps
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.routing import Mount

# ============================================================
# Configuration
# ============================================================
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise RuntimeError(
        "GITHUB_PAT or GITHUB_TOKEN environment variable must be set for private repo access."
    )

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_GRAPHQL_URL = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")

HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", "300"))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "256"))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "512"))
HTTPX_HTTP2 = os.environ.get("HTTPX_HTTP2", "0") != "0"

DEFAULT_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", "100"))

# ============================================================
# Errors
# ============================================================


class GitHubAuthError(RuntimeError):
    """Missing GitHub credentials or invalid token."""


class GitHubAPIError(RuntimeError):
    """GitHub API call failed."""


# ============================================================
# MCP server setup
# ============================================================
mcp = FastMCP("GitHub Fast MCP (private repos)", json_response=True)
WRITE_ACTIONS_APPROVED: bool = os.environ.get("GITHUB_MCP_AUTO_APPROVE", "0") != "0"


def mcp_tool(*, write_action: bool = False, **kwargs):
    """
    Compatibility wrapper for ``@mcp.tool`` that keeps write/read intent metadata.

    Older FastMCP releases reject unknown keyword arguments. This decorator stores
    the ``write_action`` flag on the original function, the tool returned by
    FastMCP, and the exported wrapper so clients can still introspect intent.
    """

    def decorator(func):
        tool = mcp.tool(**kwargs)(func)

        @wraps(func)
        async def wrapper(*args, **inner_kwargs):
            return await tool(*args, **inner_kwargs)

        for obj in (func, tool, wrapper):
            setattr(obj, "write_action", write_action)
        return wrapper

    return decorator


# ============================================================
# Shared clients
# ============================================================
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
        if "http2" in str(exc):
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


def _ensure_github_client() -> httpx.AsyncClient:
    global _github_client
    if _github_client is None:
        _github_client = _build_client(GITHUB_API_BASE)
    return _github_client


def _ensure_external_client() -> httpx.AsyncClient:
    global _external_client
    if _external_client is None:
        _external_client = _build_client()
    return _external_client


async def _close_clients() -> None:
    global _github_client, _external_client
    try:
        if _github_client is not None:
            await _github_client.aclose()
    finally:
        _github_client = None
    try:
        if _external_client is not None:
            await _external_client.aclose()
    finally:
        _external_client = None


# ============================================================
# Auth helpers
# ============================================================
async def _ensure_write_allowed(action: str) -> None:
    if not WRITE_ACTIONS_APPROVED:
        raise GitHubAuthError(
            "Write operations (commit files, create branches, open PRs) need to be "
            "authorized for this session. Call authorize_github_session or "
            "authorize_write_actions once to proceed."
        )


# ============================================================
# HTTP helpers
# ============================================================
async def _github_request(
    method: str,
    path_or_url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
    full_url: bool = False,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    client = _ensure_github_client()
    url = path_or_url if full_url or path_or_url.startswith("http") else path_or_url
    response = await client.request(
        method.upper(),
        url,
        params=params,
        json=json_body,
        headers=headers or {},
        timeout=httpx.Timeout(timeout) if timeout else None,
    )

    result: Dict[str, Any] = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
        "bytes": response.content,
    }
    try:
        result["text"] = response.text
    except Exception:
        result["text"] = None

    if "application/json" in response.headers.get("content-type", "").lower():
        try:
            result["json"] = response.json()
        except Exception:
            pass

    if response.status_code >= 400:
        body_sample = (
            result.get("text")
            or (result.get("bytes") and result["bytes"][:1000])
            or b""
        )
        raise GitHubAPIError(
            f"GitHub API error {response.status_code} for {method} {url}: "
            f"{str(body_sample)[:1000]}"
        )
    return result


async def _external_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Union[str, bytes, Dict[str, Any]]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    client = _ensure_external_client()
    request_kwargs: Dict[str, Any] = {}
    if headers:
        request_kwargs["headers"] = headers
    if isinstance(body, (str, bytes)):
        request_kwargs["content"] = body
    elif body is not None:
        request_kwargs["json"] = body

    response = await client.request(
        method.upper(),
        url,
        timeout=httpx.Timeout(timeout) if timeout else None,
        **request_kwargs,
    )

    result: Dict[str, Any] = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
        "bytes": response.content,
    }
    try:
        result["text"] = response.text
    except Exception:
        result["text"] = None

    if "application/json" in response.headers.get("content-type", "").lower():
        try:
            result["json"] = response.json()
        except Exception:
            pass

    if response.status_code >= 400:
        body_sample = (
            result.get("text")
            or (result.get("bytes") and result["bytes"][:1000])
            or b""
        )
        raise RuntimeError(
            f"HTTP error {response.status_code} when fetching {url}: "
            f"{str(body_sample)[:1000]}"
        )
    return result


# ============================================================
# MCP tools - auth
# ============================================================
@mcp_tool(write_action=False)
@mcp.tool(write_action=False)
async def authorize_github_session() -> str:
    """Approve GitHub MCP write actions for the current session."""

    global WRITE_ACTIONS_APPROVED
    WRITE_ACTIONS_APPROVED = True
    return (
        "GitHub MCP write actions authorized for this session. You can now commit files, "
        "create branches, and open PRs without extra prompts."
    )


@mcp_tool(write_action=False)
@mcp.tool(write_action=False)
async def authorize_write_actions() -> str:
    """Alias for authorize_github_session for clarity."""

    return await authorize_github_session()


# ============================================================
# MCP tools - low level GitHub access
# ============================================================
@mcp_tool(write_action=True)
@mcp.tool(write_action=True)
async def github_request(
    method: str,
    path: str,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Any] = None,
) -> Dict[str, Any]:
    method_upper = method.upper()
    if method_upper not in {"GET", "HEAD", "OPTIONS"}:
        await _ensure_write_allowed(f"{method_upper} {path}")
    return await _github_request(method_upper, path, params=query, json_body=body)


@mcp_tool(write_action=True)
@mcp.tool(write_action=True)
async def github_graphql(
    query: str, variables: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    await _ensure_write_allowed("GraphQL request")
    client = _ensure_github_client()
    payload = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    response = await client.post(GITHUB_GRAPHQL_URL, json=payload)
    if response.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub GraphQL error {response.status_code}: {response.text[:1000]}"
        )
    try:
        return {
            "status": response.status_code,
            "url": str(response.url),
            "json": response.json(),
            "text": response.text,
        }
    except Exception:
        return {"status": response.status_code, "url": str(response.url), "text": response.text}


@mcp_tool(write_action=False)
@mcp.tool(write_action=False)
async def fetch_url(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Union[str, bytes, Dict[str, Any]]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """Fetch an arbitrary URL on the web (follows redirects)."""

    return await _external_fetch(url, method=method, headers=headers, body=body, timeout=timeout)


@mcp_tool(write_action=False)
async def sanity_check(ctx: Context[ServerSession, None]) -> str:
    """Simple tool to validate MCP server wiring."""

    await ctx.debug("sanity_check tool was called successfully.")
    return "GitHub Fast MCP server is up and responding."


# ============================================================
# MCP tools - GitHub introspection
# ============================================================
@mcp_tool(write_action=False)
async def github_rate_limit() -> Dict[str, Any]:
    return await _github_request("GET", "/rate_limit")


@mcp_tool(write_action=False)
async def github_whoami() -> Dict[str, Any]:
    return await _github_request("GET", "/user")


@mcp_tool(write_action=False)
async def list_repo_tree(
    repository_full_name: str,
    ref: str = "main",
    recursive: bool = True,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    endpoint = f"/repos/{repository_full_name.strip()}/git/trees/{ref}"
    params = {"recursive": 1} if recursive else None
    result = await _github_request("GET", endpoint, params=params)
    return {"status": result["status"], "url": result["url"], "tree": result.get("json")}


@mcp_tool(write_action=False)
async def list_repo_files(
    repository_full_name: str,
    ref: str = "main",
) -> Dict[str, Any]:
    tree_result = await list_repo_tree(repository_full_name, ref=ref, recursive=True)
    tree = tree_result.get("tree") or {}
    entries = tree.get("tree") or []
    files = [entry["path"] for entry in entries if entry.get("type") == "blob"]
    return {
        "status": tree_result.get("status", 200),
        "url": tree_result.get("url"),
        "file_count": len(files),
        "files": files,
    }


@mcp_tool(write_action=False)
async def search_code(
    repository_full_name: str,
    query: str,
    per_page: int = 50,
    page: int = 1,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    search_query = f"{query} repo:{repository_full_name}"
    params = {"q": search_query, "per_page": max(1, min(per_page, 100)), "page": max(1, page)}
    result = await _github_request("GET", "/search/code", params=params)
    return {
        "status": result["status"],
        "url": result["url"],
        "search_query": search_query,
        "results": result.get("json"),
    }


# ============================================================
# MCP tools - file fetch helpers
# ============================================================
async def _decode_contents_item(item: Dict[str, Any], encoding: str = "utf-8") -> Dict[str, Any]:
    if not item:
        raise GitHubAPIError("Empty contents item.")
    item_type = item.get("type")
    if item_type == "dir":
        return {"type": "dir", "entries": item}
    if item_type == "file":
        if item.get("encoding") == "base64":
            raw = base64.b64decode(item.get("content", ""))
            try:
                return {"type": "file", "text": raw.decode(encoding), "size": len(raw)}
            except Exception:
                return {"type": "file", "bytes": raw, "size": len(raw)}
        content = item.get("content", "")
        return {"type": "file", "text": content, "size": len(content)}
    return {"type": item_type or "unknown", "json": item}


@mcp_tool(write_action=False)
async def fetch_file(
    repository_full_name: str,
    path: str,
    ref: str = "main",
    encoding: str = "utf-8",
    raw: bool = True,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")

    owner_repo = repository_full_name.strip()
    endpoint = f"/repos/{owner_repo}/contents/{path}"
    params = {"ref": ref}

    if raw:
        headers = {"Accept": "application/vnd.github.v3.raw"}
        result = await _github_request(
            "GET", endpoint, params=params, headers=headers, full_url=False, timeout=timeout
        )
        return {
            "status": result["status"],
            "url": result["url"],
            "text": result.get("text"),
            "bytes": result.get("bytes"),
        }

    result = await _github_request(
        "GET", endpoint, params=params, headers=None, full_url=False, timeout=timeout
    )
    item = result.get("json")
    if item is None:
        raise GitHubAPIError(
            f"Unexpected response when fetching file: {result.get('text') or result.get('bytes')}"
        )
    decoded = await _decode_contents_item(item, encoding=encoding)
    return {"status": result["status"], "url": result["url"], "decoded": decoded}


@mcp_tool(write_action=False)
async def fetch_files(
    repository_full_name: str,
    paths: List[str],
    ref: str = "main",
    encoding: str = "utf-8",
    raw: bool = True,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    if not isinstance(paths, list):
        raise ValueError("paths must be a list of file paths.")
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))

    async def _fetch_one(p: str) -> Tuple[str, Dict[str, Any]]:
        async with semaphore:
            try:
                res = await fetch_file(
                    repository_full_name,
                    p,
                    ref=ref,
                    encoding=encoding,
                    raw=raw,
                    timeout=timeout,
                )
                return p, {"ok": True, "result": res}
            except Exception as exc:  # noqa: BLE001
                return p, {"ok": False, "error": str(exc)}

    results = dict(await asyncio.gather(*[_fetch_one(p) for p in paths]))
    successes = {k: v for k, v in results.items() if v.get("ok")}
    failures = {k: v for k, v in results.items() if not v.get("ok")}
    return {
        "count": len(paths),
        "succeeded": len(successes),
        "failed": len(failures),
        "results": results,
    }


# ============================================================
# MCP tools - write operations
# ============================================================
@mcp_tool(write_action=True)
async def commit_file(
    repository_full_name: str,
    path: str,
    content: str,
    message: str,
    branch: str = "main",
    encoding: str = "utf-8",
    sha: Optional[str] = None,
    committer_name: Optional[str] = None,
    committer_email: Optional[str] = None,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_write_allowed(f"commit {path}")

    owner_repo = repository_full_name.strip()
    endpoint = f"/repos/{owner_repo}/contents/{path}"
    target_branch = branch.strip() or "main"

    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(content.encode(encoding)).decode("utf-8"),
        "branch": target_branch,
    }
    if committer_name and committer_email:
        payload["committer"] = {"name": committer_name, "email": committer_email}

    file_sha = sha
    if file_sha is None:
        try:
            existing = await _github_request("GET", endpoint, params={"ref": target_branch})
            file_sha = (existing.get("json") or {}).get("sha")
        except GitHubAPIError:
            file_sha = None

    if file_sha:
        payload["sha"] = file_sha

    result = await _github_request("PUT", endpoint, json_body=payload)
    return {"status": result["status"], "url": result["url"], "result": result.get("json")}


async def _create_git_blob(
    repository_full_name: str,
    *,
    content: Union[str, bytes],
    encoding: str = "utf-8",
    use_base64: bool = True,
) -> str:
    owner_repo = repository_full_name.strip()
    payload: Dict[str, Any] = {"encoding": "base64" if use_base64 else "utf-8"}
    if isinstance(content, bytes):
        encoded = (
            base64.b64encode(content).decode("utf-8") if use_base64 else content.decode(encoding)
        )
    else:
        encoded = base64.b64encode(content.encode(encoding)).decode("utf-8") if use_base64 else content
    payload["content"] = encoded

    result = await _github_request("POST", f"/repos/{owner_repo}/git/blobs", json_body=payload)
    blob_sha = (result.get("json") or {}).get("sha")
    if not blob_sha:
        raise GitHubAPIError("Failed to create git blob")
    return blob_sha


async def _create_git_tree(
    repository_full_name: str,
    *,
    base_tree: str,
    entries: List[Dict[str, Any]],
) -> str:
    owner_repo = repository_full_name.strip()
    payload = {"base_tree": base_tree, "tree": entries}
    result = await _github_request("POST", f"/repos/{owner_repo}/git/trees", json_body=payload)
    tree_sha = (result.get("json") or {}).get("sha")
    if not tree_sha:
        raise GitHubAPIError("Failed to create git tree")
    return tree_sha


async def _create_git_commit(
    repository_full_name: str,
    *,
    message: str,
    tree_sha: str,
    parent_sha: str,
) -> str:
    owner_repo = repository_full_name.strip()
    payload = {"message": message, "tree": tree_sha, "parents": [parent_sha]}
    result = await _github_request("POST", f"/repos/{owner_repo}/git/commits", json_body=payload)
    commit_sha = (result.get("json") or {}).get("sha")
    if not commit_sha:
        raise GitHubAPIError("Failed to create git commit")
    return commit_sha


async def _update_branch_ref(
    repository_full_name: str,
    *,
    branch: str,
    sha: str,
    force: bool = False,
) -> Dict[str, Any]:
    owner_repo = repository_full_name.strip()
    endpoint = f"/repos/{owner_repo}/git/refs/heads/{branch}"
    return await _github_request("PATCH", endpoint, json_body={"sha": sha, "force": force})


async def _get_branch_sha(repository_full_name: str, branch: str) -> str:
    endpoint = f"/repos/{repository_full_name.strip()}/git/refs/heads/{branch}"
    result = await _github_request("GET", endpoint)
    sha = ((result.get("json") or {}).get("object") or {}).get("sha")
    if not sha:
        raise GitHubAPIError(f"Could not resolve branch '{branch}' for {repository_full_name}.")
    return sha


@mcp_tool(write_action=True)
async def commit_files_git(
    repository_full_name: str,
    files: List[Dict[str, Any]],
    message: str,
    branch: str = "main",
    encoding: str = "utf-8",
    force: bool = False,
    use_base64: bool = True,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    if not isinstance(files, list) or not files:
        raise ValueError("files must be a non-empty list of {path, content} items")

    await _ensure_write_allowed("commit multiple files")

    owner_repo = repository_full_name.strip()
    target_branch = branch.strip() or "main"

    head_sha = await _get_branch_sha(owner_repo, target_branch)
    commit_info = await _github_request("GET", f"/repos/{owner_repo}/git/commits/{head_sha}")
    base_tree_sha = ((commit_info.get("json") or {}).get("tree") or {}).get("sha")
    if not base_tree_sha:
        raise GitHubAPIError(
            f"Could not resolve base tree for branch '{target_branch}' in {owner_repo}."
        )

    tree_entries: List[Dict[str, Any]] = []
    created_blobs: List[Dict[str, str]] = []

    for item in files:
        if not isinstance(item, dict):
            raise ValueError("each file entry must be a dict with 'path' and 'content'")
        path = item.get("path")
        content = item.get("content")
        mode = item.get("mode", "100644")
        if not path or content is None:
            raise ValueError("each file entry must include path and content")

        blob_sha = await _create_git_blob(owner_repo, content=content, encoding=encoding, use_base64=use_base64)
        created_blobs.append({"path": path, "sha": blob_sha})
        tree_entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob_sha})

    new_tree_sha = await _create_git_tree(owner_repo, base_tree=base_tree_sha, entries=tree_entries)
    new_commit_sha = await _create_git_commit(
        owner_repo, message=message, tree_sha=new_tree_sha, parent_sha=head_sha
    )
    ref_update = await _update_branch_ref(owner_repo, branch=target_branch, sha=new_commit_sha, force=force)

    return {
        "status": ref_update.get("status", 200),
        "branch": target_branch,
        "commit_sha": new_commit_sha,
        "tree_sha": new_tree_sha,
        "blobs": created_blobs,
        "ref_update": ref_update.get("json"),
    }


@mcp_tool(write_action=True)
async def create_branch(
    repository_full_name: str,
    new_branch: str,
    from_ref: str = "main",
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_write_allowed(f"create branch {new_branch}")

    base_sha = await _get_branch_sha(repository_full_name, from_ref)
    payload = {"ref": f"refs/heads/{new_branch}", "sha": base_sha}
    endpoint = f"/repos/{repository_full_name.strip()}/git/refs"
    result = await _github_request("POST", endpoint, json_body=payload)
    return {"status": result["status"], "url": result["url"], "result": result.get("json")}


@mcp_tool(write_action=True)
async def create_pull_request(
    repository_full_name: str,
    title: str,
    head: str,
    base: str = "main",
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_write_allowed(f"create PR from {head} to {base}")

    payload: Dict[str, Any] = {"title": title, "head": head, "base": base, "draft": draft}
    if body:
        payload["body"] = body

    endpoint = f"/repos/{repository_full_name.strip()}/pulls"
    result = await _github_request("POST", endpoint, json_body=payload)
    return {"status": result["status"], "url": result["url"], "pull_request": result.get("json")}


# ============================================================
# ASGI wiring
# ============================================================
app = Starlette(routes=[Mount("/", app=mcp.sse_app())])
app.add_event_handler("shutdown", lambda: asyncio.create_task(_close_clients()))

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
