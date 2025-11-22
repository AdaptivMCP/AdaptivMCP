import os
from typing import Any, Dict, Optional

import httpx
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.routing import Mount

# ============================================================
# Configuration / GitHub credentials
# ============================================================

# Read the GitHub token from environment variables. Render will
# provide these at process start, so this is safe to do at import.
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_GRAPHQL_URL = os.environ.get("GITHUB_GRAPHQL_URL", "https://api.github.com/graphql")


class GitHubAuthError(RuntimeError):
    """Raised when GitHub credentials are missing."""


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API call fails."""


# Create the MCP server instance
mcp = FastMCP("GitHub Full Access MCP", json_response=True)


# ============================================================
# Low-level HTTP helpers
# ============================================================
async def _github_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Low-level helper to call the GitHub REST API.
    """

    token = GITHUB_TOKEN
    if not token:
        raise GitHubAuthError(
            "GITHUB_PAT or GITHUB_TOKEN env var is not set. "
            "Set it to a GitHub personal access token with the scopes you need."
        )

    if not path.startswith("/"):
        path = "/" + path

    url = f"{GITHUB_API_BASE}{path}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        # Use the recommended GitHub API version header
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.request(
            method.upper(),
            url,
            headers=headers,
            params=params,
            json=json_body,
        )

    result: Dict[str, Any] = {
        "status": resp.status_code,
        "url": str(resp.url),
        "headers": dict(resp.headers),
    }

    text = resp.text
    ct = resp.headers.get("content-type", "")

    if "application/json" in ct.lower():
        try:
            result["json"] = resp.json()
        except ValueError:
            result["text"] = text
    else:
        result["text"] = text

    if resp.status_code >= 400:
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for {method} {url}: {text[:1000]}"
        )

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
    Make an arbitrary call to the GitHub REST API.

    Parameters
    ----------
    method:
        HTTP method, e.g. 'GET', 'POST', 'PATCH', 'PUT', 'DELETE'.
    path:
        Path relative to the REST API base URL, e.g. '/user',
        '/repos/{owner}/{repo}/issues'.
    query:
        Optional query parameters object.
    body:
        Optional JSON request body.
    """
    return await _github_request(method, path, params=query, json_body=body)


@mcp.tool()
async def github_graphql(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Call the GitHub GraphQL API.

    Parameters
    ----------
    query:
        GraphQL query string.
    variables:
        Optional variables object.
    """
    token = GITHUB_TOKEN
    if not token:
        raise GitHubAuthError(
            "GITHUB_PAT or GITHUB_TOKEN env var is not set. "
            "Set it to a GitHub personal access token with the scopes you need."
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    payload: Dict[str, Any] = {"query": query}
    if variables is not None:
        payload["variables"] = variables

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(GITHUB_GRAPHQL_URL, headers=headers, json=payload)

    text = resp.text
    result: Dict[str, Any] = {
        "status": resp.status_code,
        "url": str(resp.url),
        "headers": dict(resp.headers),
    }

    try:
        result["json"] = resp.json()
    except ValueError:
        result["text"] = text

    if resp.status_code >= 400 or "errors" in result.get("json", {}):
        raise GitHubAPIError(
            f"GitHub GraphQL error {resp.status_code}: {text[:1000]}"
        )

    return result


@mcp.tool()
async def fetch_url(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    Generic outbound HTTP(S) fetch tool for the connector.

    Parameters
    ----------
    url:
        Full URL to fetch (e.g., "https://api.example.com/data").
    method:
        HTTP method to use (default: "GET").
    headers:
        Optional dict of HTTP headers to include.
    body:
        Optional request body. If a list/dict is provided it will be sent as JSON.
        Otherwise it will be sent as form/text body.
    timeout:
        Request timeout in seconds (default: 30.0).

    Returns
    -------
    dict
        { "status": int, "url": str, "headers": dict, "json": obj | "text": str }

    Notes
    -----
    - The tool mirrors the error-handling style of the GitHub helpers: if the
      remote responds with HTTP >= 400 a RuntimeError is raised with the
      response snippet for diagnostic purposes.
    - Render allows outbound internet access by default; ensure your service
      has any required firewall/Egress rules if you have custom networking.
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        req_kwargs: Dict[str, Any] = {}
        if headers:
            req_kwargs["headers"] = headers
        # If body is a dict or list send JSON, otherwise send as data
        if isinstance(body, (dict, list)):
            req_kwargs["json"] = body
        elif body is not None:
            req_kwargs["data"] = body

        resp = await client.request(method.upper(), url, **req_kwargs)

    result: Dict[str, Any] = {
        "status": resp.status_code,
        "url": str(resp.url),
        "headers": dict(resp.headers),
    }

    ct = resp.headers.get("content-type", "")
    text = resp.text
    if "application/json" in ct.lower():
        try:
            result["json"] = resp.json()
        except ValueError:
            result["text"] = text
    else:
        result["text"] = text

    if resp.status_code >= 400:
        raise RuntimeError(
            f"HTTP error {resp.status_code} when fetching {url}: {text[:1000]}"
        )

    return result


@mcp.tool()
async def sanity_check(ctx: Context[ServerSession, None]) -> str:
    """
    Simple tool to verify that the MCP server is reachable and working.
    """
    await ctx.debug("sanity_check tool was called successfully.")
    return "GitHub MCP server is up and responding to tool calls."


# ============================================================
# ASGI app with SSE endpoints
# ============================================================

# Mount the FastMCP SSE app at the ROOT.
# This exposes:
#   - GET  /sse       (SSE stream)
#   - POST /messages/ (MCP messages)
# on the same port Render provides via $PORT.
app = Starlette(
    routes=[
        Mount("/", app=mcp.sse_app()),
    ]
)

if __name__ == "__main__":
    import uvicorn

    # Render binds your service to the PORT env var and requires 0.0.0.0
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
