# main.py
"""
Fast GitHub MCP connector optimized for private repositories.
- Uses a pooled httpx.AsyncClient with default Authorization header.
- fetch_file defaults to raw content (application/vnd.github.v3.raw) for minimal overhead.
- fetch_files supports concurrent reads.
- fetch_url allows arbitrary web checks.
- HTTP/2 is OFF by default (no h2 dependency required). To enable HTTP/2, install
  httpx[http2] and set HTTPX_HTTP2=1 in the environment.

Extended tools:
- github_rate_limit: inspect GitHub API rate limits.
- github_whoami: see which GitHub user the token belongs to.
- list_repo_tree: expose /git/trees for a repo at a ref.
- list_repo_files: flat list of file paths from the tree.
- search_code: GitHub code search scoped to a repo.
"""

import os
import base64
import asyncio
from typing import Any, Dict, Optional, Union, List, Tuple

import httpx
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.routing import Mount

# ============================================================
# Configuration
# ============================================================
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    # For this deployment we require a token (private repo access).
    raise RuntimeError("GITHUB_PAT or GITHUB_TOKEN environment variable must be set for private repo access.")

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_GRAPHQL_URL = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")

# Connection / performance tuning (tweak for your environment)
HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", "300"))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "256"))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "512"))

# IMPORTANT: default http2 OFF to avoid requiring `h2`.
# If you later install `httpx[http2]`, you can set HTTPX_HTTP2=1 to enable it.
HTTPX_HTTP2 = os.environ.get("HTTPX_HTTP2", "0") != "0"

# Default concurrency used by fetch_files
DEFAULT_CONCURRENCY = int(os.environ.get("FETCH_FILES_CONCURRENCY", "100"))

# ============================================================
# Errors
# ============================================================
class GitHubAuthError(RuntimeError):
    """Missing GitHub credentials or invalid token."""


class GitHubAPIError(RuntimeError):
    """GitHub API call failed."""


# ============================================================
# MCP server
# ============================================================
mcp = FastMCP("GitHub Fast MCP (private repos)", json_response=True)

# Session-scoped permission switch. The GitHub tools will refuse to run until the
# session is explicitly approved via the authorize_github_session tool. This
# avoids repeated per-call confirmations while still keeping a single opt-in per
# session.
SESSION_APPROVED: bool = False

# ============================================================
# Shared pooled clients
# ============================================================
_github_client: Optional[httpx.AsyncClient] = None
_external_client: Optional[httpx.AsyncClient] = None


def _make_github_headers() -> Dict[str, str]:
    # Set token and recommended headers once (keeps per-request overhead minimal).
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "GitHub-Fast-MCP/1.0",
        "Connection": "keep-alive",
    }


async def _ensure_session_allowed() -> None:
    """Require that the session has been explicitly authorized once."""
    if not SESSION_APPROVED:
        raise GitHubAuthError(
            "GitHub MCP tools need to be authorized for this session. "
            "Call authorize_github_session once to proceed."
        )


def _ensure_github_client() -> httpx.AsyncClient:
    """
    Return a shared AsyncClient configured for GitHub API use.
    The client has base_url set to GITHUB_API_BASE and includes the Authorization header.
    """
    global _github_client
    if _github_client is None:
        limits = httpx.Limits(
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
            max_connections=HTTPX_MAX_CONNECTIONS,
        )

        # Try to create client with http2 if requested; if the environment
        # is missing h2, fall back to http1.1 automatically.
        http2_enabled = HTTPX_HTTP2
        try:
            _github_client = httpx.AsyncClient(
                base_url=GITHUB_API_BASE,
                timeout=httpx.Timeout(HTTPX_TIMEOUT),
                limits=limits,
                follow_redirects=True,
                http2=http2_enabled,
                headers=_make_github_headers(),
                trust_env=False,
            )
        except RuntimeError as e:
            # Typical error if http2=True but h2 package is not installed.
            if "http2=True" in str(e) or "h2" in str(e):
                # Fallback: logically disable http2 and retry with http1.1
                _github_client = httpx.AsyncClient(
                    base_url=GITHUB_API_BASE,
                    timeout=httpx.Timeout(HTTPX_TIMEOUT),
                    limits=limits,
                    follow_redirects=True,
                    http2=False,
                    headers=_make_github_headers(),
                    trust_env=False,
                )
            else:
                raise
    return _github_client


def _ensure_external_client() -> httpx.AsyncClient:
    """
    Return a shared AsyncClient for external (non-GitHub) web checks.
    """
    global _external_client
    if _external_client is None:
        limits = httpx.Limits(
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
            max_connections=HTTPX_MAX_CONNECTIONS,
        )
        http2_enabled = HTTPX_HTTP2
        try:
            _external_client = httpx.AsyncClient(
                timeout=httpx.Timeout(HTTPX_TIMEOUT),
                limits=limits,
                follow_redirects=True,
                http2=http2_enabled,
                headers={"User-Agent": "GitHub-Fast-MCP/1.0"},
                trust_env=False,
            )
        except RuntimeError as e:
            if "http2=True" in str(e) or "h2" in str(e):
                _external_client = httpx.AsyncClient(
                    timeout=httpx.Timeout(HTTPX_TIMEOUT),
                    limits=limits,
                    follow_redirects=True,
                    http2=False,
                    headers={"User-Agent": "GitHub-Fast-MCP/1.0"},
                    trust_env=False,
                )
            else:
                raise
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
# Low-level request helpers
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
    """
    Low-level request to GitHub using the pooled client.
    - If full_url True, path_or_url is treated as an absolute URL and used directly.
    - Otherwise path_or_url is appended to the client's base_url.
    Returns a dict containing status, url, headers, text, bytes (if available), json (if JSON).
    """
    client = _ensure_github_client()
    request_url = path_or_url if full_url or path_or_url.lower().startswith("http") else path_or_url
    req_headers = headers or {}
    resp = await client.request(
        method.upper(),
        request_url,
        params=params,
        json=json_body,
        headers=req_headers,
        timeout=httpx.Timeout(timeout) if timeout else None,
    )

    result: Dict[str, Any] = {"status": resp.status_code, "url": str(resp.url), "headers": dict(resp.headers)}
    result["bytes"] = resp.content
    try:
        result["text"] = resp.text
    except Exception:
        result["text"] = None

    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        try:
            result["json"] = resp.json()
        except Exception:
            pass

    if resp.status_code >= 400:
        body_sample = (result.get("text") or (result.get("bytes") and result["bytes"][:1000]) or b"")
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for {method} {request_url}: {str(body_sample)[:1000]}"
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
    """
    Generic external HTTP(s) fetch; follows redirects and uses pooled client.
    """
    client = _ensure_external_client()
    request_kwargs: Dict[str, Any] = {}
    if headers:
        request_kwargs["headers"] = headers
    if isinstance(body, (str, bytes)):
        request_kwargs["content"] = body
    elif body is not None:
        request_kwargs["json"] = body

    resp = await client.request(
        method.upper(),
        url,
        timeout=httpx.Timeout(timeout) if timeout else None,
        **request_kwargs,
    )

    result: Dict[str, Any] = {
        "status": resp.status_code,
        "url": str(resp.url),
        "headers": dict(resp.headers),
        "bytes": resp.content,
    }
    try:
        result["text"] = resp.text
    except Exception:
        result["text"] = None

    content_type = resp.headers.get("content-type", "")
    if "application/json" in content_type.lower():
        try:
            result["json"] = resp.json()
        except Exception:
            pass

    if resp.status_code >= 400:
        body_sample = (result.get("text") or (result.get("bytes") and result["bytes"][:1000]) or b"")
        raise RuntimeError(f"HTTP error {resp.status_code} when fetching {url}: {str(body_sample)[:1000]}")
    return result


# ============================================================
# MCP tools (exposed) - low-level
# ============================================================
@mcp.tool()
async def authorize_github_session() -> str:
    """Approve GitHub MCP actions for the current session to avoid repeated prompts."""

    global SESSION_APPROVED
    SESSION_APPROVED = True
    return "GitHub MCP tools authorized for this session."


@mcp.tool()
async def github_request(
    method: str,
    path: str,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Generic request to the GitHub REST API using pooled client.
    - path: path under the API (e.g. '/user' or '/repos/{owner}/{repo}/issues')
    """
    await _ensure_session_allowed()
    headers = None  # default client headers include Authorization and Accept
    return await _github_request(method, path, params=query, json_body=body, headers=headers)


@mcp.tool()
async def github_graphql(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Run a GraphQL query against GitHub's GraphQL API using pooled client.
    """
    await _ensure_session_allowed()
    client = _ensure_github_client()
    payload = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    resp = await client.post(GITHUB_GRAPHQL_URL, json=payload)
    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub GraphQL error {resp.status_code}: {resp.text[:1000]}")
    try:
        return {"status": resp.status_code, "url": str(resp.url), "json": resp.json(), "text": resp.text}
    except Exception:
        return {"status": resp.status_code, "url": str(resp.url), "text": resp.text}


@mcp.tool()
async def fetch_url(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Union[str, bytes, Dict[str, Any]]] = None,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Fetch an arbitrary URL on the web (follows redirects). Useful for "checking the web".
    """
    return await _external_fetch(url, method=method, headers=headers, body=body, timeout=timeout)


@mcp.tool()
async def sanity_check(ctx: Context[ServerSession, None]) -> str:
    """
    Simple tool to validate MCP server wiring.
    """
    await ctx.debug("sanity_check tool was called successfully.")
    return "GitHub Fast MCP server is up and responding."


# ============================================================
# MCP tools (exposed) - higher-level / introspection
# ============================================================
@mcp.tool()
async def github_rate_limit() -> Dict[str, Any]:
    """
    Inspect current GitHub REST API rate limits for this token.
    """
    await _ensure_session_allowed()
    return await _github_request("GET", "/rate_limit")


@mcp.tool()
async def github_whoami() -> Dict[str, Any]:
    """
    Return information about the authenticated GitHub user for this token.
    """
    await _ensure_session_allowed()
    return await _github_request("GET", "/user")


@mcp.tool()
async def list_repo_tree(
    repository_full_name: str,
    ref: str = "main",
    recursive: bool = True,
) -> Dict[str, Any]:
    """
    Return the raw Git tree for a repository at a given ref (branch, tag, or tree SHA).
    This uses the /git/trees endpoint.
    """
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_session_allowed()
    owner_repo = repository_full_name.strip()
    endpoint = f"/repos/{owner_repo}/git/trees/{ref}"
    params: Optional[Dict[str, Any]] = {"recursive": 1} if recursive else None
    result = await _github_request("GET", endpoint, params=params)
    return {
        "status": result["status"],
        "url": result["url"],
        "tree": result.get("json"),
    }


@mcp.tool()
async def list_repo_files(
    repository_full_name: str,
    ref: str = "main",
) -> Dict[str, Any]:
    """
    Return a flat list of file paths from the git tree at the given ref.
    Useful for quickly enumerating all files in a repo.
    """
    await _ensure_session_allowed()
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


@mcp.tool()
async def search_code(
    repository_full_name: str,
    query: str,
    per_page: int = 50,
    page: int = 1,
) -> Dict[str, Any]:
    """
    Perform a GitHub code search scoped to a specific repository.
    - query: the search query string (without the 'repo:' qualifier; it will be added automatically).
    """
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_session_allowed()

    q = f"{query} repo:{repository_full_name}"
    params = {
        "q": q,
        "per_page": max(1, min(per_page, 100)),
        "page": max(1, page),
    }
    result = await _github_request("GET", "/search/code", params=params)
    return {
        "status": result["status"],
        "url": result["url"],
        "search_query": q,
        "results": result.get("json"),
    }


# ============================================================
# High-level file fetch helpers optimized for private repos
# ============================================================
async def _decode_contents_api_item(item: Dict[str, Any], encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Decode a JSON item from /contents endpoint into text/bytes.
    """
    if not item:
        raise GitHubAPIError("Empty contents item.")
    t = item.get("type")
    if t == "dir":
        return {"type": "dir", "entries": item}
    if t == "file":
        if item.get("encoding") == "base64":
            raw = base64.b64decode(item.get("content", ""))
            try:
                text = raw.decode(encoding)
                return {"type": "file", "text": text, "size": len(raw)}
            except Exception:
                return {"type": "file", "bytes": raw, "size": len(raw)}
        else:
            return {"type": "file", "text": item.get("content", ""), "size": len(item.get("content", ""))}
    return {"type": t or "unknown", "json": item}


@mcp.tool()
async def fetch_file(
    repository_full_name: str,
    path: str,
    ref: str = "main",
    encoding: str = "utf-8",
    raw: bool = True,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Fetch a single file from a private repo quickly.
    - repository_full_name: 'owner/repo'
    - path: path inside repo
    - ref: branch/commit/tag
    - raw: if True, request raw content via Accept: application/vnd.github.v3.raw (fast)
    Returns a dict: { status, url, text?, bytes?, decoded? }
    """
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_session_allowed()

    owner_repo = repository_full_name.strip()
    endpoint = f"/repos/{owner_repo}/contents/{path}"
    params = {"ref": ref}

    if raw:
        headers = {"Accept": "application/vnd.github.v3.raw"}
        result = await _github_request(
            "GET",
            endpoint,
            params=params,
            headers=headers,
            full_url=False,
            timeout=timeout,
        )
        return {
            "status": result["status"],
            "url": result["url"],
            "text": result.get("text"),
            "bytes": result.get("bytes"),
        }
    else:
        headers = None
        result = await _github_request(
            "GET",
            endpoint,
            params=params,
            headers=headers,
            full_url=False,
            timeout=timeout,
        )
        item = result.get("json")
        if item is None:
            raise GitHubAPIError(f"Unexpected response when fetching file: {result.get('text') or result.get('bytes')}")
        decoded = await _decode_contents_api_item(item, encoding=encoding)
        return {"status": result["status"], "url": result["url"], "decoded": decoded}


@mcp.tool()
async def fetch_files(
    repository_full_name: str,
    paths: List[str],
    ref: str = "main",
    encoding: str = "utf-8",
    raw: bool = True,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Fetch many files concurrently from a private repo.
    Returns mapping: path -> {"ok": True, "result": {...}} or {"ok": False, "error": "..."}
    """
    if not isinstance(paths, list):
        raise ValueError("paths must be a list of file paths.")
    await _ensure_session_allowed()
    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _one(p: str) -> Tuple[str, Dict[str, Any]]:
        async with sem:
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
            except Exception as e:
                return p, {"ok": False, "error": str(e)}

    tasks = [asyncio.create_task(_one(p)) for p in paths]
    results = await asyncio.gather(*tasks)
    return {k: v for k, v in results}


@mcp.tool()
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
    """
    Create or update a file in a GitHub repository using the Contents API.
    If sha is omitted and the file already exists, the current sha is fetched automatically.
    """

    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")
    await _ensure_session_allowed()

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


# ============================================================
# ASGI app wiring and graceful shutdown
# ============================================================
app = Starlette(routes=[Mount("/", app=mcp.sse_app())])

# Ensure pooled clients are closed on shutdown
app.add_event_handler("shutdown", lambda: asyncio.create_task(_close_clients()))

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
