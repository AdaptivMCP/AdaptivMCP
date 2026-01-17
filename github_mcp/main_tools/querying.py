from __future__ import annotations

import sys
from typing import Any, Dict, Literal, Optional

from github_mcp.http_clients import (
    _external_client_instance as _default_external_client_instance,
)
from github_mcp.http_clients import (
    _get_concurrency_semaphore as _default_get_concurrency_semaphore,
)
from github_mcp.redaction import redact_any
from github_mcp.server import (
    _github_request as _default_github_request,
)
from github_mcp.server import (
    _structured_tool_error as _default_structured_tool_error,
)


def _resolve_main_helper(name: str, default):
    """Resolve an optional helper override from the entry module.

    The server may be executed as `main` or as `__main__` depending on the
    hosting environment. This helper keeps the compatibility surface stable
    without requiring hard imports.
    """
    for mod_name in ("main", "__main__"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        if hasattr(mod, name):
            return getattr(mod, name)
    return default


async def graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a GitHub GraphQL query using the shared HTTP client."""

    github_request = _resolve_main_helper("_github_request", _default_github_request)
    structured_tool_error = _resolve_main_helper(
        "_structured_tool_error", _default_structured_tool_error
    )

    payload = {"query": query, "variables": variables or {}}
    try:
        result = await github_request(
            "POST",
            "/graphql",
            json_body=payload,
        )
    except Exception as exc:  # noqa: BLE001
        return structured_tool_error(
            exc,
            context="graphql_query",
        )

    # main.py historically returned only the parsed JSON for graphql_query.
    payload_json = result.get("json")
    if isinstance(payload_json, dict):
        return payload_json
    return structured_tool_error(
        RuntimeError("GraphQL response did not include a JSON object"),
        context="graphql_query",
    )


async def fetch_url(url: str) -> Dict[str, Any]:
    """Fetch an arbitrary HTTP/HTTPS URL via the shared external client."""

    external_client_instance = _resolve_main_helper(
        "_external_client_instance", _default_external_client_instance
    )
    get_concurrency_semaphore = _resolve_main_helper(
        "_get_concurrency_semaphore", _default_get_concurrency_semaphore
    )
    structured_tool_error = _resolve_main_helper(
        "_structured_tool_error", _default_structured_tool_error
    )

    client = external_client_instance()
    async with get_concurrency_semaphore():
        try:
            resp = await client.get(url)
        except Exception as e:  # noqa: BLE001
            return structured_tool_error(
                e,
                context="fetch_url",
                path=url,
            )

    # Avoid returning potentially sensitive headers and redact secrets that may
    # appear in response bodies.
    headers = dict(resp.headers)
    for k in list(headers.keys()):
        if str(k).lower() in {"authorization", "cookie", "set-cookie", "proxy-authorization"}:
            headers.pop(k, None)

    return redact_any(
        {
            "status_code": resp.status_code,
            "headers": headers,
            "content": resp.text,
        }
    )


async def search(
    query: str,
    search_type: Literal["code", "repositories", "issues", "commits", "users"] = "code",
    per_page: int = 30,
    page: int = 1,
    sort: Optional[str] = None,
    order: Optional[Literal["asc", "desc"]] = None,
) -> Dict[str, Any]:
    """Perform GitHub search queries (code, repos, issues, commits, or users)."""

    github_request = _resolve_main_helper("_github_request", _default_github_request)
    structured_tool_error = _resolve_main_helper(
        "_structured_tool_error", _default_structured_tool_error
    )

    allowed_types = {"code", "repositories", "issues", "commits", "users"}
    if search_type not in allowed_types:
        return structured_tool_error(
            ValueError(f"search_type must be one of {sorted(allowed_types)}"),
            context="search",
        )
    if per_page <= 0:
        return structured_tool_error(ValueError("per_page must be > 0"), context="search")
    if page <= 0:
        return structured_tool_error(ValueError("page must be > 0"), context="search")

    # GitHub Search API constraints: per_page max 100.
    per_page = min(int(per_page), 100)

    # GitHub's Search API only returns up to 1,000 results. We therefore cap
    # pages to 10 when per_page=100 (and proportionally otherwise).
    max_page = max(1, 1000 // max(1, per_page))
    if page > max_page:
        return structured_tool_error(
            ValueError(
                f"page is too large for GitHub Search API (max page for per_page={per_page} is {max_page})"
            ),
            context="search",
        )

    params: Dict[str, Any] = {"q": query, "per_page": per_page, "page": page}
    if sort:
        params["sort"] = sort
    if order is not None:
        allowed_order = {"asc", "desc"}
        if order not in allowed_order:
            return structured_tool_error(
                ValueError("order must be 'asc' or 'desc'"),
                context="search",
            )
        params["order"] = order

    headers = None
    if search_type == "commits":
        headers = {
            "Accept": "application/vnd.github+json,application/vnd.github.cloak-preview+json"
        }

    try:
        result = await github_request(
            "GET",
            f"/search/{search_type}",
            params=params,
            headers=headers,
        )
        # Search results can include snippets that contain secrets; redact.
        return redact_any(result)
    except Exception as exc:  # noqa: BLE001
        return structured_tool_error(
            exc,
            context="search",
        )
