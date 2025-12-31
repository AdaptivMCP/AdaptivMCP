"""Render observability helpers.

User experience goals
- Return dict payloads (not raw lists) where possible so the MCP layer can attach
  consistent user-friendly summary fields.
- Preserve raw Render responses under stable keys.

"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from github_mcp.config import (
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    RENDER_API_BASE,
)
from github_mcp.mcp_server.errors import AdaptivToolError


def _render_api_key() -> str:
    key = os.environ.get("RENDER_API_KEY")
    if not key:
        raise AdaptivToolError(
            "RENDER_API_KEY is not set.",
            hint="Set RENDER_API_KEY in your environment and retry.",
            code="missing_render_api_key",
            category="config",
        )
    return key


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_render_api_key()}", "Accept": "application/json"}


def _client() -> httpx.AsyncClient:
    limits = httpx.Limits(max_connections=HTTPX_MAX_CONNECTIONS, max_keepalive_connections=HTTPX_MAX_KEEPALIVE)
    return httpx.AsyncClient(timeout=HTTPX_TIMEOUT, limits=limits)


async def _get_json(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
    url = f"{RENDER_API_BASE}{path}"
    async with _client() as client:
        resp = await client.get(url, headers=_headers(), params=params)
        if resp.status_code >= 400:
            raise AdaptivToolError(
                f"Render API request failed ({resp.status_code}).",
                hint="Check Render credentials and request parameters, then retry.",
                code="render_api_error",
                category="provider",
            )
        return resp.json()


async def resolve_owner_id_from_service_id(service_id: str) -> Optional[str]:
    """Attempt to resolve ownerId from a service id."""
    try:
        data = await _get_json(f"/services/{service_id}")
    except Exception:
        return None
    if isinstance(data, dict):
        owner = data.get("ownerId")
        if isinstance(owner, str) and owner:
            return owner
    return None


async def list_render_logs(
    ownerId: Optional[str] = None,
    resource: Optional[List[str]] = None,
    level: Optional[List[str]] = None,
    type: Optional[List[str]] = None,
    text: Optional[List[str]] = None,
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    direction: Optional[str] = None,
    limit: Optional[int] = 100,
) -> Dict[str, Any]:
    """Fetch recent logs from Render.

    Returns:
    {
      "logs": <raw list payload>,
      "log_count": <int|None>,
      "controller_log": ["Render logs: N entries"],
    }
    """

    if not ownerId:
        ownerId = os.environ.get("RENDER_OWNER_ID")

    if not ownerId:
        service_id = os.environ.get("RENDER_SERVICE_ID")
        if service_id:
            ownerId = await resolve_owner_id_from_service_id(service_id)

    if not ownerId:
        raise AdaptivToolError(
            "Render /logs requires an ownerId and none was provided.",
            hint="Pass ownerId or set RENDER_OWNER_ID (or set RENDER_SERVICE_ID so ownerId can be resolved).",
            code="missing_owner_id",
            category="config",
        )

    params: Dict[str, Any] = {"ownerId": ownerId}
    if resource:
        params["resource"] = resource
    if level:
        params["level"] = level
    if type:
        params["type"] = type
    if text:
        params["text"] = text
    if startTime:
        params["startTime"] = startTime
    if endTime:
        params["endTime"] = endTime
    if direction:
        params["direction"] = direction
    if limit is not None:
        params["limit"] = int(limit)

    logs = await _get_json("/logs", params=params)
    count = len(logs) if isinstance(logs, list) else None

    return {
        "logs": logs,
        "log_count": count,
        "controller_log": [f"Render logs: {count} entries" if count is not None else "Render logs: fetched"],
    }


async def get_render_metrics(
    metricTypes: List[str],
    resourceId: Optional[str] = None,
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    resolution: Optional[int] = None,
) -> Dict[str, Any]:
    """Fetch basic Render service metrics."""

    if not metricTypes:
        raise AdaptivToolError(
            "metricTypes is required.",
            hint="Provide at least one metric type.",
            code="missing_metric_types",
            category="validation",
        )

    if not resourceId:
        resourceId = os.environ.get("RENDER_SERVICE_ID")

    if not resourceId:
        raise AdaptivToolError(
            "resourceId is required and RENDER_SERVICE_ID is not set.",
            hint="Pass resourceId or set RENDER_SERVICE_ID.",
            code="missing_resource_id",
            category="config",
        )

    params: Dict[str, Any] = {"metricTypes": metricTypes, "resourceId": resourceId}
    if startTime:
        params["startTime"] = startTime
    if endTime:
        params["endTime"] = endTime
    if resolution is not None:
        params["resolution"] = int(resolution)

    data = await _get_json("/metrics", params=params)
    if not isinstance(data, dict):
        data = {"metrics": data}
    return data
