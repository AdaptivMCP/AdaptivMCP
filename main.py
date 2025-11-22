import os
from typing import Any, Dict, Optional

import httpx
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import JSONResponse

# ============================================================
# Configuration / GitHub credentials
# ============================================================

# Read GitHub PAT from environment. You can use either name.
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")

# Support GitHub Enterprise if you ever need it.
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

    - method: HTTP method, e.g. "GET", "POST", "PATCH", "PUT", "DELETE"
    - path: path relative to GITHUB_API_BASE, e.g. "/user", "/repos/{owner}/{repo}/issues"
    - params: optional query parameters
    - json_body: optional JSON body

    Returns a dict with status, url, headers, and json/text.
    Raises GitHubAPIError on non-2xx responses.
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
        # GitHub asks clients to send an explicit API version header.
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
        # Expose rich error information to ChatGPT, but do not leak the token.
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
        Path relative to the REST API base URL. Examples:
        - '/user'
        - '/users/{username}'
        - '/repos/{owner}/{repo}/issues'
    query:
        Optional query parameters as an object (will be serialized to the query string).
    body:
        Optional JSON request body as an object.

    Notes for the model
    -------------------
    - Use https://docs.github.com/en/rest for the list of endpoints.
    - Always provide the path relative to the base URL (GITHUB_API_BASE), not a full URL.
    - This tool can create/update/delete repos, files, issues, pull requests, etc.,
      depending on the token scopes.
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
        The GraphQL query string.
    variables:
        Optional variables as an object.

    Returns
    -------
    Dict with fields 'status', 'url', 'headers', and 'json'/'text'.

    Notes for the model
    -------------------
    - Use https://docs.github.com/graphql for schema documentation.
    - Prefer this for complex cross-object queries or bulk operations.
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

    # Treat HTTP errors or GraphQL "errors" as failures.
    if resp.status_code >= 400 or "errors" in result.get("json", {}):
        raise GitHubAPIError(
            f"GitHub GraphQL error {resp.status_code}: {text[:1000]}"
        )

    return result


@mcp.tool()
async def sanity_check(ctx: Context[ServerSession, None]) -> str:
    """
    Simple tool to verify that the MCP server is reachable and working.

    Returns a short success string and logs a debug message.
    """
    await ctx.debug("sanity_check tool was called successfully.")
    return "GitHub MCP server is up and responding to tool calls."


# ============================================================
# ASGI app with SSE endpoint at /sse for ChatGPT
# ============================================================

# Build the SSE MCP ASGI application.
mcp_app = mcp.sse_app()

# Starlette app that:
# - Exposes MCP SSE endpoint at /sse  (ChatGPT will connect here)
# - Exposes a simple JSON health endpoint at /
app = Starlette(
    routes=[
        Mount("/sse", app=mcp_app),
        Route(
            "/",
            endpoint=lambda request: JSONResponse(
                {"status": "ok", "message": "GitHub MCP server is running", "sse_path": "/sse"}
            ),
        ),
    ]
)


if __name__ == "__main__":
    import uvicorn

    # Render will provide PORT as an environment variable.
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
