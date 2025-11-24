"""
GitHub Fast MCP server exposing common read/write utilities for private repositories.

The server keeps write/read intent metadata via a compatibility-friendly decorator so
clients can accurately label mutating operations even on FastMCP versions that do not
recognize the ``write_action`` argument.
"""
from __future__ import annotations

import asyncio
import base64
import os
from functools import wraps
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route

# ============================================================
# Configuration
# ============================================================
GITHUB_TOKEN = os.environ.get("GITHUB_PAT") or os.environ.get("GITHUB_TOKEN")
if not GITHUB_TOKEN:
    raise RuntimeError(
        "GITHUB_PAT or GITHUB_TOKEN environment variable must be set for private repo access."
    )

GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")
HTTPX_TIMEOUT = float(os.environ.get("HTTPX_TIMEOUT", "120"))
HTTPX_MAX_KEEPALIVE = int(os.environ.get("HTTPX_MAX_KEEPALIVE", "100"))
HTTPX_MAX_CONNECTIONS = int(os.environ.get("HTTPX_MAX_CONNECTIONS", "200"))
HTTPX_HTTP2 = os.environ.get("HTTPX_HTTP2", "0") != "0"

# ============================================================
# Errors
# ============================================================


class GitHubAuthError(RuntimeError):
    """Raised when a write action is attempted without prior approval."""


class GitHubAPIError(RuntimeError):
    """Raised when GitHub returns a non-success status code."""


# ============================================================
# MCP setup and decorator compatibility
# ============================================================
mcp = FastMCP("GitHub Fast MCP", json_response=True)
WRITE_ACTIONS_APPROVED: bool = os.environ.get("GITHUB_MCP_AUTO_APPROVE", "0") != "0"


def mcp_tool(*, write_action: bool = False, **kwargs):
    """
    Wrapper around ``@mcp.tool`` that preserves write/read intent metadata.

    Older FastMCP releases reject unknown keyword arguments, so we attach the
    ``write_action`` flag to the original function, the decorated tool, and a thin
    wrapper that forwards calls. Clients can then introspect any of these objects to
    determine whether a tool mutates state.
    """

    def decorator(func):
        try:
            tool = mcp.tool(write_action=write_action, **kwargs)(func)
        except TypeError:
            tool = mcp.tool(**kwargs)(func)

        @wraps(func)
        async def wrapper(*args, **inner_kwargs):
            return await tool(*args, **inner_kwargs)

        for obj in (func, tool, wrapper):
            setattr(obj, "write_action", write_action)
            try:
                obj.__dict__["write_action"] = write_action
            except Exception:
                pass
        return wrapper

    return decorator


# ============================================================
# HTTP clients
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
        # Some environments disable HTTP/2; gracefully fall back to HTTP/1.1
        if "http2" in str(exc).lower():
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


def _github_client_instance() -> httpx.AsyncClient:
    global _github_client
    if _github_client is None:
        _github_client = _build_client(GITHUB_API_BASE)
    return _github_client


def _external_client_instance() -> httpx.AsyncClient:
    global _external_client
    if _external_client is None:
        _external_client = _build_client()
    return _external_client


async def _close_clients() -> None:
    global _github_client, _external_client
    if _github_client is not None:
        await _github_client.aclose()
        _github_client = None
    if _external_client is not None:
        await _external_client.aclose()
        _external_client = None


# ============================================================
# Helpers
# ============================================================
async def _ensure_write_allowed(action: str) -> None:
    if not WRITE_ACTIONS_APPROVED:
        raise GitHubAuthError(
            "Write operations require prior approval. Call authorize_write_actions before "
            f"attempting to {action}."
        )


async def _github_request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Any] = None,
) -> Dict[str, Any]:
    client = _github_client_instance()
    response = await client.request(method.upper(), path, params=params, json=json_body)
    result = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
    }
    try:
        result["json"] = response.json()
    except Exception:
        result["text"] = response.text
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub API error {response.status_code}: {response.text}")
    return result


# ============================================================
# Tools (read)
# ============================================================
@mcp_tool(write_action=False)
async def authorize_write_actions(approved: bool = True) -> Dict[str, Any]:
    """Enable write operations for the current MCP session."""
    global WRITE_ACTIONS_APPROVED
    WRITE_ACTIONS_APPROVED = bool(approved)
    return {"write_actions_enabled": WRITE_ACTIONS_APPROVED}


@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    """Return the current GitHub rate limit status."""
    return await _github_request("GET", "/rate_limit")

@mcp_tool(write_action=False)
async def get_rate_limit() -> Dict[str, Any]:
    """Return the current GitHub rate limit status."""
    return await _github_request("GET", "/rate_limit")

@mcp_tool(write_action=False)
async def get_repository(full_name: str) -> Dict[str, Any]:
    """Fetch repository metadata (owner/repo)."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    return await _github_request("GET", f"/repos/{full_name.strip()}")


@mcp_tool(write_action=False)
async def list_branches(full_name: str, per_page: int = 100, page: int = 1) -> Dict[str, Any]:
    """List branches for a repository."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    params = {"per_page": per_page, "page": page}
    return await _github_request("GET", f"/repos/{full_name.strip()}/branches", params=params)


@mcp_tool(write_action=False)
async def get_file_contents(full_name: str, path: str, ref: str = "main") -> Dict[str, Any]:
    """Fetch a file's decoded text contents from a repository."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    result = await _github_request(
        "GET", f"/repos/{full_name.strip()}/contents/{path.lstrip('/')}", params={"ref": ref}
    )
    data = result.get("json", {})
    decoded: Optional[str] = None
    if isinstance(data, dict) and data.get("encoding") == "base64" and "content" in data:
        decoded = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    return {"status": result["status"], "path": path, "ref": ref, "decoded": decoded, "raw": data}


@mcp_tool(write_action=False)
async def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch an external URL (for diagnostics)."""
    client = _external_client_instance()
    response = await client.get(url)
    return {"status": response.status_code, "url": str(response.url), "text": response.text}


@mcp_tool(write_action=False)
async def list_workflow_runs(
    full_name: str,
    *,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    event: Optional[str] = None,
    per_page: int = 20,
    page: int = 1,
) -> Dict[str, Any]:
    """List GitHub Actions workflow runs for a repository."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    params: Dict[str, Any] = {"per_page": per_page, "page": page}
    if branch:
        params["branch"] = branch
    if status:
        params["status"] = status
    if event:
        params["event"] = event
    return await _github_request("GET", f"/repos/{full_name.strip()}/actions/runs", params=params)


@mcp_tool(write_action=False)
async def get_workflow_run(full_name: str, run_id: int) -> Dict[str, Any]:
    """Get details for a specific GitHub Actions workflow run."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    return await _github_request(
        "GET", f"/repos/{full_name.strip()}/actions/runs/{run_id}"
    )


@mcp_tool(write_action=False)
async def list_workflow_run_jobs(
    full_name: str, run_id: int, per_page: int = 50, page: int = 1
) -> Dict[str, Any]:
    """List jobs for a GitHub Actions workflow run."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    params = {"per_page": per_page, "page": page}
    return await _github_request(
        "GET", f"/repos/{full_name.strip()}/actions/runs/{run_id}/jobs", params=params
    )


@mcp_tool(write_action=False)
async def get_job_logs(full_name: str, job_id: int) -> Dict[str, Any]:
    """Retrieve raw logs for a GitHub Actions job."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    client = _github_client_instance()
    response = await client.get(f"/repos/{full_name.strip()}/actions/jobs/{job_id}/logs")
    result = {
        "status": response.status_code,
        "url": str(response.url),
        "headers": dict(response.headers),
    }
    try:
        # Some environments return text/plain; others may return JSON error bodies.
        result["text"] = response.text
    except Exception:
        result["content"] = base64.b64encode(response.content).decode("utf-8")
    if response.status_code >= 400:
        raise GitHubAPIError(f"GitHub API error {response.status_code}: {result.get('text', '')}")
    return result


# ============================================================
# Tools (write)
# ============================================================
@mcp_tool(write_action=True)
async def create_branch(full_name: str, new_branch: str, from_ref: str = "main") -> Dict[str, Any]:
    """Create a new branch from an existing reference."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    await _ensure_write_allowed(f"create branch {new_branch}")

    ref_info = await _github_request("GET", f"/repos/{full_name.strip()}/git/refs/heads/{from_ref}")
    sha = ref_info.get("json", {}).get("object", {}).get("sha")
    if not sha:
        raise GitHubAPIError("Unable to resolve source ref SHA")
    payload = {"ref": f"refs/heads/{new_branch}", "sha": sha}
    return await _github_request("POST", f"/repos/{full_name.strip()}/git/refs", json_body=payload)


@mcp_tool(write_action=True)
async def commit_file(
    full_name: str,
    path: str,
    message: str,
    content: Optional[str] = None,
    *,
    content_url: Optional[str] = None,
    branch: str = "main",
    sha: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update a file in a repository.

    The caller can provide the file contents directly via ``content`` or supply a
    ``content_url`` that will be fetched with the shared external client. This
    avoids JSON escaping limits when committing large files through MCP tool
    transports that struggle with big string arguments.
    """
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    await _ensure_write_allowed(f"commit file {path}")

    if content is None and content_url is None:
        raise ValueError("Either content or content_url must be provided")
    if content is not None and content_url is not None:
        raise ValueError("Provide content or content_url, but not both")

    body_content = content
    if content_url is not None:
        parsed = urlparse(content_url)
        if parsed.scheme in ("http", "https"):
            client = _external_client_instance()
            response = await client.get(content_url)
            if response.status_code >= 400:
                raise GitHubAPIError(
                    f"Failed to fetch content from {content_url}: {response.status_code}"
                )
            body_content = response.text
        else:
            # Treat as local filesystem path (including file:// URIs)
            file_path = parsed.path if parsed.scheme == "file" else content_url
            if not os.path.isfile(file_path):
                raise FileNotFoundError(f"Content path not found: {file_path}")
            with open(file_path, "r", encoding="utf-8") as fp:
                body_content = fp.read()

    assert body_content is not None  # for type checkers

    payload: Dict[str, Any] = {
        "message": message,
        "content": base64.b64encode(body_content.encode("utf-8")).decode("utf-8"),
        "branch": branch,
    }
    if sha:
        payload["sha"] = sha
    return await _github_request(
        "PUT", f"/repos/{full_name.strip()}/contents/{path.lstrip('/')}", json_body=payload
    )


@mcp_tool(write_action=True)
async def create_pull_request(
    full_name: str,
    title: str,
    head: str,
    base: str = "main",
    body: Optional[str] = None,
    draft: bool = False,
) -> Dict[str, Any]:
    """Open a pull request."""
    if "/" not in full_name:
        raise ValueError("full_name must be in 'owner/repo' format")
    await _ensure_write_allowed(f"open PR from {head} to {base}")

    payload: Dict[str, Any] = {"title": title, "head": head, "base": base, "draft": draft}
    if body:
        payload["body"] = body
    return await _github_request("POST", f"/repos/{full_name.strip()}/pulls", json_body=payload)


# ============================================================
# ASGI wiring
# ============================================================
_sse_app = mcp.sse_app()


async def _sse_mount(scope, receive, send):
    """ASGI wrapper for the MCP SSE app that accepts POST/HEAD for compatibility."""

    if scope.get("type") != "http":
        return await _sse_app(scope, receive, send)

    method = scope.get("method", "GET").upper()
    if method in {"POST", "HEAD"}:  # normalize to GET for FastMCP SSE handler
        scope = dict(scope)
        scope["method"] = "GET"

    if method == "OPTIONS":
        response = PlainTextResponse("OK", status_code=204)
        await response(scope, receive, send)
        return

    if method not in {"GET", "POST", "HEAD"}:
        response = PlainTextResponse("Method Not Allowed", status_code=405)
        await response(scope, receive, send)
        return

    return await _sse_app(scope, receive, send)


routes = [
    Route(
        "/",
        lambda request: PlainTextResponse(
            "GitHub Fast MCP server active. Connect to /sse for the event stream.",
            status_code=200,
        ),
        methods=["GET", "HEAD"],
    ),
    Mount("/sse", app=_sse_mount),
]

app = Starlette(routes=routes)
app.add_event_handler("shutdown", lambda: asyncio.create_task(_close_clients()))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
