from __future__ import annotations

import sys
from typing import Any, Dict, Literal, Optional

from github_mcp.http_clients import (
    _external_client_instance as _default_external_client_instance,
    _get_concurrency_semaphore as _default_get_concurrency_semaphore,
)
from github_mcp.server import (
    _github_request as _default_github_request,
    _structured_tool_error as _default_structured_tool_error,
)


def _resolve_main_helper(name: str, default):
    main_mod = sys.modules.get("main")
    return getattr(main_mod, name, default)


async def graphql_query(query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Execute a GitHub GraphQL query using the shared HTTP client."""

    github_request = _resolve_main_helper("_github_request", _default_github_request)

    payload = {"query": query, "variables": variables or {}}
    result = await github_request(
        "POST",
        "/graphql",
        json_body=payload,
    )

    # main.py historically returned only the parsed JSON for graphql_query.
    return result.get("json")


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
                str(e),
                context="fetch_url",
                path=url,
            )

    return {
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "content": resp.text,
    }


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

    allowed_types = {"code", "repositories", "issues", "commits", "users"}
    if search_type not in allowed_types:
        raise ValueError(f"search_type must be one of {sorted(allowed_types)}")
    if per_page <= 0:
        raise ValueError("per_page must be > 0")
    if page <= 0:
        raise ValueError("page must be > 0")

    params: Dict[str, Any] = {"q": query, "per_page": per_page, "page": page}
    if sort:
        params["sort"] = sort
    if order is not None:
        allowed_order = {"asc", "desc"}
        if order not in allowed_order:
            raise ValueError("order must be 'asc' or 'desc'")
        params["order"] = order

    return await github_request("GET", f"/search/{search_type}", params=params)
