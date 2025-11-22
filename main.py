import os
from typing import Any, Dict, Optional, Union

import httpx
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.routing import Mount

# ============================================================
# Configuration / GitHub credentials
# ============================================================

# Read the GitHub token from environment variables. Render / your
# runtime should provide one of these at process start.
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
GITHUB_GRAPHQL_URL = os.environ.get(
    "GITHUB_GRAPHQL_URL", "https://api.github.com/graphql"
)

# ============================================================
# Errors
# ============================================================


class GitHubAuthError(RuntimeError):
    """Raised when GitHub credentials are missing."""


class GitHubAPIError(RuntimeError):
    """Raised when a GitHub API call fails."""


# ============================================================
# MCP server instance
# ============================================================

mcp = FastMCP("GitHub Full Access MCP", json_response=True)

# ============================================================
# Low-level GitHub HTTP helper
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

    This uses the configured personal access token and base URL.
    """

    token = GITHUB_TOKEN
    if not token:
        raise GitHubAuthError(
            "GITHUB_PAT or GITHUB_TOKEN env var is not set. "
            "Set it to a GitHub personal access token with the scopes you need."
        )

    if not path.startswith("/"):
        path = "/" + path

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        # Recommended GitHub API version header
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(
        base_url=GITHUB_API_BASE, timeout=30.0, follow_redirects=True
    ) as client:
        resp = await client.request(
            method.upper(),
            path,
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
        # Keep a trimmed body in the error message for debugging
        raise GitHubAPIError(
            f"GitHub API error {resp.status_code} for {method} {path}: {text[:1000]}"
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
    Arbitrary GitHub REST API call.

    Parameters
    ----------
    method:
        HTTP method, e.g. "GET", "POST", "PATCH", "PUT", "DELETE".
    path:
        Path relative to the REST API base URL, e.g. "/user",
        "/repos/{owner}/{repo}/issues".
    query:
        Optional querystring parameters.
    body:
        Optional JSON body to send.

    Returns
    -------
    dict
        { "status": int, "url": str, "headers": dict, "json"?: any, "text"?: str }
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
        Optional GraphQL variables dict.

    Returns
    -------
    dict
        { "status": int, "url": str, "headers": dict, "json"?: any, "text"?: str }
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
    body: Optional[Union[Dict[str, Any], list, str, bytes]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    Generic outbound HTTP(S) fetch tool for research and integrations.

    Parameters
    ----------
    url:
        Full URL to fetch (e.g. "https://www.google.com/search?q=test").
    method:
        HTTP method to use (default: "GET").
    headers:
        Optional dict of HTTP headers.
    body:
        Optional request body:
        - If dict or list: sent as JSON.
        - If str/bytes: sent as raw body.
    timeout:
        Request timeout in seconds (default: 30.0).

    Returns
    -------
    dict
        { "status": int, "url": str, "headers": dict, "json"?: any, "text"?: str }
    """
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        request_kwargs: Dict[str, Any] = {}
        if headers:
            request_kwargs["headers"] = headers

        # Shape body appropriately for httpx
        if isinstance(body, (dict, list)):
            request_kwargs["json"] = body
        elif isinstance(body, (str, bytes)):
            request_kwargs["content"] = body
        elif body is not None:
            # Fallback to string representation
            request_kwargs["content"] = str(body)

        resp = await client.request(method.upper(), url, **request_kwargs)

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
        # Mirror the GitHub helper behaviour: raise on HTTP errors so
        # the client gets a clear failure signal, but still include
        # clipped response text for debugging / diagnostics.
        raise RuntimeError(
            f"HTTP error {resp.status_code} when fetching {url}: {text[:1000]}"
        )

    return result


@mcp.tool()
async def sanity_check(ctx: Context[ServerSession, None]) -> str:
    """
    Simple tool to verify MCP server wiring from the client side.
    """
    await ctx.debug("sanity_check tool was called successfully.")
    return "GitHub MCP server is up and responding to tool calls."


# ============================================================
# ASGI app wiring
# ============================================================

# Mount the FastMCP SSE app at the root. Render / infra will expose
# this on the configured PORT.
app = Starlette(
    routes=[
        Mount("/", app=mcp.sse_app()),
    ]
)

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
