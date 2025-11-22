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
    """
    return await _github_request(method, path, params=query, json_body=body)


@mcp.tool()
async def github_graphql(
    query: str,
    variables: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Call the GitHub GraphQL API.
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
async def sanity_check(ctx: Context[ServerSession, None]) -> str:
    """
    Simple tool to verify that the MCP server is reachable and working.
    """
    await ctx.debug("sanity_check tool was called successfully.")
    return "GitHub MCP server is up and responding to tool calls."


# ============================================================
# ASGI app with SSE endpoints
# ============================================================

# IMPORTANT: mount the SSE app at the ROOT.
# This exposes:
#   - GET /sse      (SSE stream)
#   - POST /messages/ (MCP messages)
# exactly as the MCP SDK expects. 
app = Starlette(
    routes=[
        Mount("/", app=mcp.sse_app()),
    ]
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
