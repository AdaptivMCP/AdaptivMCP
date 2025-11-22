# main.py -- Streamlined, fast GitHub MCP connector (single pooled client)
import os
import base64
import asyncio
from typing import Any, Dict, Optional, Union, List

import httpx
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.routing import Mount

# ============================================================
# Configuration / GitHub credentials / runtime toggles
# ============================================================
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_GRAPHQL_URL = os.environ.get(
    "GITHUB_GRAPHQL_URL", "https://api.github.com/graphql"
)

# If set to "1", the server will accept requests without interactive
# server-side gating. This allows flow-through usage in trusted deployments.
GITHUB_BYPASS_PROMPT = os.environ.get("GITHUB_BYPASS_PROMPT", "0") == "1"

# Tunable pool settings for the shared httpx client
HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", "30.0"))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "20"))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "100"))

# ============================================================
# Errors
# ============================================================
class GitHubAuthError(RuntimeError):
    """Raised when GitHub credentials are required but missing."""

class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API call fails."""

# ============================================================
# MCP server instance
# ============================================================
mcp = FastMCP("GitHub Fast MCP Connector", json_response=True)

# ============================================================
# Global pooled httpx.AsyncClient for low-latency requests
# ============================================================
_github_client: Optional[httpx.AsyncClient] = None

def _ensure_github_client() -> httpx.AsyncClient:
    """
    Ensure a shared AsyncClient exists and return it.
    Reusing this client reduces latency by preserving keep-alive connections
    and avoiding repeated client construction.
    """
    global _github_client
    if _github_client is None:
        limits = httpx.Limits(
            max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
            max_connections=HTTPX_MAX_CONNECTIONS,
        )
        _github_client = httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            timeout=HTTPX_TIMEOUT,
            limits=limits,
            follow_redirects=True,
        )
    return _github_client

async def _shutdown_client() -> None:
    global _github_client
    if _github_client is not None:
        try:
            await _github_client.aclose()
        except Exception:
            pass
        _github_client = None

# ============================================================
# Helper headers / request wrapper
# ============================================================
def _build_github_headers(accept: Optional[str] = None, require_token: bool = True) -> Dict[str, str]:
    """
    Build Authorization and Accept headers. If require_token is True and a token
    is missing, raise GitHubAuthError unless GITHUB_BYPASS_PROMPT is set.
    """
    token = GITHUB_TOKEN
    if require_token and not token and not GITHUB_BYPASS_PROMPT:
        raise GitHubAuthError(
            "GITHUB_PAT or GITHUB_TOKEN env var is not set. "
            "Set it to a GitHub personal access token with the scopes you need."
        )

    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    # Default Accept if not provided
    headers["Accept"] = accept or "application/vnd.github+json"
    headers["X-GitHub-Api-Version"] = "2022-11-28"
    headers["Connection"] = "keep-alive"
    return headers

async def _github_request(
    method: str,
    path_or_url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    # If full_url is True, path_or_url is treated as a full URL and won't be joined with base_url.
    full_url: bool = False,
) -> Dict[str, Any]:
    """
    Low-level GitHub request using the shared client.

    If full_url is True, `path_or_url` is treated as an absolute URL (useful for raw.githubusercontent.com).
    Otherwise it is appended to the client's base_url (GITHUB_API_BASE).
    """
    client = _ensure_github_client()

    request_url = path_or_url if full_url or path_or_url.lower().startswith("http") else path_or_url
    # If not full_url and the path doesn't begin with '/', ensure it's correct for the client's base_url.
    if not full_url and not request_url.startswith("/"):
        request_url = "/" + request_url

    resp = await client.request(method.upper(), request_url, headers=headers, params=params, json=json_body)
    result: Dict[str, Any] = {"status": resp.status_code, "url": str(resp.url), "headers": dict(resp.headers)}
    ct = resp.headers.get("content-type", "")
    text = resp.text

    if "application/json" in ct.lower():
        try:
            result["json"] = resp.json()
        except ValueError:
            result["text"] = text
    else:
        # For raw responses (text/binary), keep text and raw bytes when useful.
        result["text"] = text
        try:
            result["bytes"] = resp.content
        except Exception:
            pass

    if resp.status_code >= 400:
        raise GitHubAPIError(f"GitHub API error {resp.status_code} for {method} {request_url}: {text[:1000]}")

    return result

# ============================================================
# MCP tools
# ============================================================
@mcp.tool()
async def github_request(
    method: str,
    path: str,
    query: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generic GitHub REST API tool that uses the pooled client.
    """
    headers = _build_github_headers()
    return await _github_request(method, path, params=query, json_body=body, headers=headers)

@mcp.tool()
async def github_graphql(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute a GraphQL query against GitHub's GraphQL endpoint using the pooled client.
    """
    token = GITHUB_TOKEN
    if not token and not GITHUB_BYPASS_PROMPT:
        raise GitHubAuthError("GITHUB token is required for GraphQL calls.")
    headers = _build_github_headers(accept="application/vnd.github+json", require_token=False)
    payload: Dict[str, Any] = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    client = _ensure_github_client()
    resp = await client.post(GITHUB_GRAPHQL_URL, headers=headers, json=payload)
    text = resp.text
    result: Dict[str, Any] = {"status": resp.status_code, "url": str(resp.url), "headers": dict(resp.headers)}
    try:
        result["json"] = resp.json()
    except ValueError:
        result["text"] = text
    if resp.status_code >= 400 or "errors" in result.get("json", {}):
        raise GitHubAPIError(f"GitHub GraphQL error {resp.status_code}: {text[:1000]}")
    return result

@mcp.tool()
async def sanity_check(ctx: Context[ServerSession, None]) -> str:
    """
    Quick check to ensure the MCP server is reachable.
    """
    await ctx.debug("sanity_check tool was called successfully.")
    return "GitHub MCP server (fast connector) is up and responding."

# ============================================================
# Fast file fetcher tools
# ============================================================

async def _decode_contents_api_item(item: Dict[str, Any], encoding: str = "utf-8") -> Dict[str, Any]:
    """
    Decode a JSON item returned by the GitHub Contents API.
    Returns a dict like {"type":"file","text":...} or {"type":"dir","entries":...}.
    """
    if item.get("type") == "dir":
        return {"type": "dir", "entries": item}
    if item.get("type") == "file":
        if item.get("encoding") == "base64":
            raw = base64.b64decode(item.get("content", ""))
            try:
                text = raw.decode(encoding)
                return {"type": "file", "text": text, "size": len(raw)}
            except Exception:
                return {"type": "file", "bytes": raw, "size": len(raw)}
        else:
            # Content returned directly
            return {"type": "file", "text": item.get("content", ""), "size": len(item.get("content", ""))}
    # Unknown / blob
    return {"type": item.get("type", "unknown"), "json": item}

@mcp.tool()
async def fetch_file(
    repository_full_name: str,
    path: str,
    ref: str = "main",
    encoding: str = "utf-8",
    raw: bool = False,
    use_cdn: bool = False,
) -> Dict[str, Any]:
    """
    Fetch a single file from a repository.
    - repository_full_name: "owner/repo"
    - path: path within repo
    - ref: branch/commit/tag
    - raw: if True, request raw content from GitHub API (Accept: application/vnd.github.v3.raw)
    - use_cdn: if True and raw is True, attempt to fetch via raw.githubusercontent.com CDN for lower latency.
      (CDN only works for public repositories; if it 404s, the code falls back to the API.)
    """
    if "/" not in repository_full_name:
        raise ValueError("repository_full_name must be 'owner/repo'")

    owner, repo = repository_full_name.split("/", 1)
    # Prefer CDN when requested (fast path). Construct absolute URL for CDN:
    if raw and use_cdn:
        # Build raw.githubusercontent.com URL: https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}
        cdn_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
        try:
            # CDN fetch does not require Authorization; allow no-auth when GITHUB_BYPASS_PROMPT set
            headers = _build_github_headers(accept="text/plain", require_token=False)
            result = await _github_request("GET", cdn_url, headers=headers, full_url=True)
            # Return text / bytes that were saved in result
            return {"status": result["status"], "url": result["url"], "text": result.get("text"), "bytes": result.get("bytes")}
        except GitHubAPIError:
            # Fallback to API call below
            pass

    # Call GitHub Contents API: /repos/{owner}/{repo}/contents/{path}?ref={ref}
    endpoint = f"/repos/{owner}/{repo}/contents/{path}"
    params = {"ref": ref}
    # If raw requested, prefer the raw Accept header
    accept_hdr = "application/vnd.github.v3.raw" if raw else None
    headers = _build_github_headers(accept=accept_hdr, require_token=False)

    result = await _github_request("GET", endpoint, params=params, headers=headers)
    # If we requested raw via API, result will contain text/bytes
    if raw and "text" in result:
        return {"status": result["status"], "url": result["url"], "text": result.get("text"), "bytes": result.get("bytes")}
    # Otherwise decode the JSON content
    item = result.get("json")
    if item is None:
        raise GitHubAPIError(f"Unexpected response when fetching file: {result.get('text')}")
    decoded = await _decode_contents_api_item(item, encoding=encoding)
    return {"status": result["status"], "url": result["url"], "decoded": decoded}

@mcp.tool()
async def fetch_files(
    repository_full_name: str,
    paths: List[str],
    ref: str = "main",
    encoding: str = "utf-8",
    raw: bool = False,
    use_cdn: bool = False,
    concurrency: int = 8,
) -> Dict[str, Any]:
    """
    Concurrently fetch multiple files. Returns a dict of path -> result.
    """
    if not isinstance(paths, list):
        raise ValueError("paths must be a list of strings")
    sem = asyncio.Semaphore(concurrency)

    async def _worker(p: str) -> (str, Dict[str, Any]):
        async with sem:
            try:
                res = await fetch_file(repository_full_name, p, ref=ref, encoding=encoding, raw=raw, use_cdn=use_cdn)
                return p, {"ok": True, "result": res}
            except Exception as e:
                return p, {"ok": False, "error": str(e)}

    tasks = [asyncio.create_task(_worker(p)) for p in paths]
    results = await asyncio.gather(*tasks)
    return {k: v for k, v in results}

# ============================================================
# ASGI app wiring + graceful shutdown
# ============================================================
app = Starlette(routes=[Mount("/", app=mcp.sse_app())])

# Register shutdown handler to close shared client
app.add_event_handler("shutdown", lambda: asyncio.create_task(_shutdown_client()))

# If run directly, use uvicorn
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
