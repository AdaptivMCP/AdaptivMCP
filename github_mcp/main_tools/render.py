from __future__ import annotations

from typing import Any, Dict, Optional

from github_mcp.render_api import render_request


async def list_render_owners(cursor: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """List Render owners (workspaces + personal owners).

 Render's API exposes workspaces via the "owners" collection.
 """

    params: Dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    return await render_request("GET", "/owners", params=params)


async def list_render_services(
    owner_id: Optional[str] = None,
    cursor: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """List Render services.

 Supports optional filtering by ownerId when provided.
 """

    params: Dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    if owner_id:
        params["ownerId"] = owner_id
    return await render_request("GET", "/services", params=params)


async def get_render_service(service_id: str) -> Dict[str, Any]:
    """Fetch a single Render service."""

    return await render_request("GET", f"/services/{service_id}")


async def list_render_deploys(
    service_id: str,
    cursor: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """List deploys for a service."""

    params: Dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    return await render_request("GET", f"/services/{service_id}/deploys", params=params)


async def get_render_deploy(service_id: str, deploy_id: str) -> Dict[str, Any]:
    """Fetch a specific deploy."""

    return await render_request("GET", f"/services/{service_id}/deploys/{deploy_id}")


async def create_render_deploy(
    service_id: str,
    clear_cache: bool = False,
    commit_id: Optional[str] = None,
    image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Trigger a new deploy for a service."""

    body: Dict[str, Any] = {"clearCache": bool(clear_cache)}
    if commit_id:
        body["commitId"] = commit_id
    if image_url:
        body["imageUrl"] = image_url
    return await render_request(
        "POST",
        f"/services/{service_id}/deploys",
        json_body=body,
    )


async def cancel_render_deploy(service_id: str, deploy_id: str) -> Dict[str, Any]:
    """Cancel an in-progress deploy."""

    return await render_request(
        "POST",
        f"/services/{service_id}/deploys/{deploy_id}/cancel",
    )


async def rollback_render_deploy(service_id: str, deploy_id: str) -> Dict[str, Any]:
    """Roll back a service to a previous deploy."""

    return await render_request(
        "POST",
        f"/services/{service_id}/deploys/{deploy_id}/rollback",
    )


async def restart_render_service(service_id: str) -> Dict[str, Any]:
    """Restart a running service."""

    return await render_request("POST", f"/services/{service_id}/restart")


async def get_render_logs(
    resource_type: str,
    resource_id: str,
    *,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    limit: int = 200,
) -> Dict[str, Any]:
    """Fetch logs for a Render resource.

 Render's logs endpoint supports resourceType/resourceId plus time bounds.
 - resource_type examples: service, job
 - start_time/end_time: ISO8601 timestamps
 """

    params: Dict[str, Any] = {
        "resourceType": resource_type,
        "resourceId": resource_id,
        "limit": limit,
    }
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time
    return await render_request("GET", "/logs", params=params)


__all__ = [
    "cancel_render_deploy",
    "create_render_deploy",
    "get_render_deploy",
    "get_render_logs",
    "get_render_service",
    "list_render_deploys",
    "list_render_owners",
    "list_render_services",
    "restart_render_service",
    "rollback_render_deploy",
]
