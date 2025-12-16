"""Render observability helpers.

This module backs the `list_render_logs` and `get_render_metrics` tools defined in
`main.py`.

It uses Render's Public API (https://api.render.com/v1) and is optional: set
RENDER_API_KEY (or RENDER_API_TOKEN) to enable.

All functions are read-only.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import asyncio
import httpx

from github_mcp.config import (
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    RENDER_API_BASE,
    RENDER_API_KEY,
    RENDER_DEFAULT_RESOURCE,
)
from github_mcp.exceptions import UsageError


def _comma(values: Optional[List[str]]) -> Optional[str]:
    if not values:
        return None
    cleaned = [v.strip() for v in values if v and v.strip()]
    return ",".join(cleaned) if cleaned else None


def _require_api_key() -> str:
    key = (RENDER_API_KEY or '').strip()
    if not key:
        raise UsageError(
            "Render API access is not configured. Set RENDER_API_KEY (or RENDER_API_TOKEN)."
        )
    return key


def _default_resource_list() -> Optional[List[str]]:
    if not RENDER_DEFAULT_RESOURCE:
        return None
    val = str(RENDER_DEFAULT_RESOURCE).strip()
    return [val] if val else None


async def _render_get(path: str, *, params: Dict[str, Any]) -> Any:
    api_key = _require_api_key()
    base = (RENDER_API_BASE or 'https://api.render.com/v1').rstrip('/')
    url = f"{base}{path}"

    limits = httpx.Limits(
        max_connections=HTTPX_MAX_CONNECTIONS,
        max_keepalive_connections=HTTPX_MAX_KEEPALIVE,
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": "github-mcp/render-observability",
    }

    async with httpx.AsyncClient(timeout=float(HTTPX_TIMEOUT), limits=limits) as client:
        resp = await client.get(url, headers=headers, params=params)

    if resp.status_code >= 400:
        try:
            payload = resp.json()
        except Exception:  # pragma: no cover
            payload = {"error": resp.text}
        raise UsageError(f"Render API error {resp.status_code} for GET {path}: {payload}")

    return resp.json()


async def list_render_logs(
    *,
    resource: Optional[List[str]] = None,
    level: Optional[List[str]] = None,
    type: Optional[List[str]] = None,
    text: Optional[List[str]] = None,
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    direction: Optional[str] = None,
    limit: Optional[int] = 100,
) -> Any:
    """Fetch Render logs via GET /logs.

    Parameters are passed through to the Render Public API.

    If `resource` is omitted, RENDER_RESOURCE/RENDER_SERVICE_ID is used when set.
    """

    resource = resource or _default_resource_list()

    params: Dict[str, Any] = {
        "resource": _comma(resource),
        "level": _comma(level),
        "type": _comma(type),
        "text": _comma(text),
        "startTime": startTime,
        "endTime": endTime,
        "direction": direction,
        "limit": int(limit) if limit is not None else None,
    }

    params = {k: v for k, v in params.items() if v is not None and v != ""}

    return await _render_get('/logs', params=params)


_METRIC_ENDPOINTS: Dict[str, str] = {
    # Monitoring > Metrics endpoints in Render Public API reference.
    "cpu_usage": "/metrics/cpu",
    "cpu_limit": "/metrics/cpu-limit",
    "memory": "/metrics/memory",
    "memory_limit": "/metrics/memory-limit",
    "http_latency": "/metrics/http-latency",
    "http_request_count": "/metrics/http-request-count",
    "http_throughput": "/metrics/http-throughput",
    "bandwidth": "/metrics/bandwidth",
    "instance_count": "/metrics/instance-count",
}


async def get_render_metrics(
    *,
    resourceId: str,
    metricTypes: List[str],
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    resolution: Optional[int] = None,
) -> Dict[str, Any]:
    """Fetch one or more Render metrics for a resource.

    `metricTypes` values must be keys in `_METRIC_ENDPOINTS`.

    This function calls the relevant /metrics/<type> endpoints and returns a
    dict keyed by metric type.
    """

    if not resourceId or not str(resourceId).strip():
        raise UsageError('resourceId is required')

    if not metricTypes:
        raise UsageError('metricTypes must be a non-empty list')

    unknown = [m for m in metricTypes if m not in _METRIC_ENDPOINTS]
    if unknown:
        raise UsageError(
            f"Unknown metricTypes: {unknown}. Supported: {sorted(_METRIC_ENDPOINTS)}"
        )

    params_base: Dict[str, Any] = {
        # Render metrics endpoints accept 'resource' (service id, instance id, etc.).
        "resource": str(resourceId).strip(),
        "startTime": startTime,
        "endTime": endTime,
    }

    if resolution is not None:
        # Many metrics endpoints accept resolutionSeconds.
        params_base["resolutionSeconds"] = int(resolution)

    params_base = {k: v for k, v in params_base.items() if v is not None and v != ""}

    async def fetch_one(metric: str) -> Any:
        return await _render_get(_METRIC_ENDPOINTS[metric], params=dict(params_base))

    results = await asyncio.gather(
        *(fetch_one(m) for m in metricTypes),
        return_exceptions=True,
    )

    out: Dict[str, Any] = {
        "resourceId": str(resourceId).strip(),
        "startTime": startTime,
        "endTime": endTime,
        "resolution": resolution,
        "metrics": {},
    }

    for metric, res in zip(metricTypes, results):
        if isinstance(res, Exception):
            out["metrics"][metric] = {"error": str(res)}
        else:
            out["metrics"][metric] = res

    return out
