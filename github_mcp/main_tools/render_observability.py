"""Render observability helpers.

This module backs the `list_render_logs` and `get_render_metrics` tools defined in
`main.py`.

It uses Render's Public API (https://api.render.com/v1) and is optional: set
RENDER_API_KEY (or RENDER_API_TOKEN) to enable.

All functions are read-only.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from github_mcp.config import (
    HTTPX_MAX_CONNECTIONS,
    HTTPX_MAX_KEEPALIVE,
    HTTPX_TIMEOUT,
    RENDER_API_BASE,
    RENDER_API_KEY,
    RENDER_DEFAULT_RESOURCE,
    RENDER_OWNER_ID,
)
from github_mcp.exceptions import UsageError


def _comma(values: Optional[List[str]]) -> Optional[str]:
    if not values:
        return None
    cleaned = [v.strip() for v in values if v and v.strip()]
    return ",".join(cleaned) if cleaned else None


def _require_api_key() -> str:
    key = (RENDER_API_KEY or "").strip()
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


_OWNER_ID_CACHE: str | None = None
_OWNER_ID_CACHE_AT: float = 0.0
_OWNER_ID_CACHE_TTL_SECONDS = 60 * 60  # 1 hour


def _default_owner_id() -> str:
    return (RENDER_OWNER_ID or "").strip()


async def _resolve_owner_id(resource_id: str | None) -> str:
    """Resolve ownerId required by Render log endpoints.

    Priority:
      1. RENDER_OWNER_ID env var
      2. Cached lookup
      3. GET /services/:id and read ownerId
    """

    env_owner = _default_owner_id()
    if env_owner:
        return env_owner

    global _OWNER_ID_CACHE, _OWNER_ID_CACHE_AT
    now = asyncio.get_running_loop().time()
    if _OWNER_ID_CACHE and (now - _OWNER_ID_CACHE_AT) < _OWNER_ID_CACHE_TTL_SECONDS:
        return _OWNER_ID_CACHE

    rid = (resource_id or "").strip()
    if not rid:
        raise UsageError("ownerId is required (set RENDER_OWNER_ID or pass ownerId)")

    try:
        payload = await _render_get(f"/services/{rid}", params={})
    except Exception as e:
        raise UsageError(
            f"Unable to resolve ownerId for resource {rid}. Set RENDER_OWNER_ID. ({e})"
        )

    owner_id = str(payload.get("ownerId") or "").strip() if isinstance(payload, dict) else ""
    if not owner_id:
        raise UsageError(
            f"Render service lookup did not include ownerId for resource {rid}. Set RENDER_OWNER_ID."
        )

    _OWNER_ID_CACHE = owner_id
    _OWNER_ID_CACHE_AT = now
    return owner_id


async def _render_get(path: str, *, params: Dict[str, Any]) -> Any:
    api_key = _require_api_key()
    base = (RENDER_API_BASE or "https://api.render.com/v1").rstrip("/")
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
    ownerId: Optional[str] = None,
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

    If `resource` is omitted, RENDER_RESOURCE/RENDER_SERVICE_ID is used when set. If `ownerId` is omitted, the tool uses RENDER_OWNER_ID or attempts to resolve it from the service id via GET /services/:id.
    """

    resource = resource or _default_resource_list()

    # Default to application logs. Platform request logs are noisy and not usually user-facing.
    type = type or ["app"]

    rid = resource[0] if resource else None
    owner_id = str(ownerId).strip() if ownerId is not None else ""
    if not owner_id:
        owner_id = await _resolve_owner_id(rid)

    params: Dict[str, Any] = {
        "ownerId": owner_id,
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

    return await _render_get("/logs", params=params)


_METRIC_ENDPOINTS: Dict[str, str] = {
    # Monitoring > Metrics endpoints in Render Public API reference.
    "cpu_usage": "/metrics/cpu",
    "cpu_limit": "/metrics/cpu-limit",
    "cpu_target": "/metrics/cpu-target",
    "memory_usage": "/metrics/memory",
    "memory_limit": "/metrics/memory-limit",
    "memory_target": "/metrics/memory-target",
    "http_latency": "/metrics/http-latency",
    "http_request_count": "/metrics/http-requests",
    "instance_count": "/metrics/instance-count",
}


async def get_render_metrics(
    *,
    metricTypes: List[str],
    resourceId: Optional[str] = None,
    startTime: Optional[str] = None,
    endTime: Optional[str] = None,
    resolution: Optional[int] = None,
) -> Dict[str, Any]:
    """Fetch one or more Render metrics for a resource. If resourceId is omitted, uses RENDER_SERVICE_ID / RENDER_RESOURCE when set.

    `metricTypes` values must be keys in `_METRIC_ENDPOINTS`.

    This function calls the relevant /metrics/<type> endpoints and returns a
    dict keyed by metric type.
    """

    rid = str(resourceId).strip() if resourceId is not None else ""
    if not rid:
        rid = str(RENDER_DEFAULT_RESOURCE or "").strip()

    if not rid:
        raise UsageError(
            "resourceId is required (or set RENDER_SERVICE_ID / RENDER_RESOURCE in the environment)"
        )

    if not metricTypes:
        raise UsageError("metricTypes must be a non-empty list")

    unknown = [m for m in metricTypes if m not in _METRIC_ENDPOINTS]
    if unknown:
        raise UsageError(f"Unknown metricTypes: {unknown}. Supported: {sorted(_METRIC_ENDPOINTS)}")

    params_base: Dict[str, Any] = {
        # Render metrics endpoints accept 'resource' (service id, instance id, etc.).
        "resource": rid,
        "startTime": startTime,
        "endTime": endTime,
    }

    if resolution is not None:
        # Many metrics endpoints accept resolutionSeconds.
        params_base["resolutionSeconds"] = int(resolution)

    params_base = {k: v for k, v in params_base.items() if v is not None and v != ""}

    async def fetch_one(metric: str) -> Any:
        params = dict(params_base)
        # Render requires a quantile for http-latency; default to p95.
        if metric == "http_latency" and "quantile" not in params:
            params["quantile"] = "0.95"
        return await _render_get(_METRIC_ENDPOINTS[metric], params=params)

    results = await asyncio.gather(
        *(fetch_one(m) for m in metricTypes),
        return_exceptions=True,
    )

    out: Dict[str, Any] = {
        "resourceId": rid,
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


async def get_render_health_summary(
    *,
    resourceId: str | None = None,
    minutes: int = 30,
) -> dict[str, object]:
    """Return a user-facing health summary for the Render service.

    This is meant for assistants to self-tune (timeouts, concurrency) and to warn
    before hitting resource limits.
    """

    import datetime as _dt

    end = _dt.datetime.now(tz=_dt.timezone.utc)
    start = end - _dt.timedelta(minutes=max(1, int(minutes)))

    start_iso = start.isoformat()
    end_iso = end.isoformat()

    payload = await get_render_metrics(
        metricTypes=[
            "cpu_usage",
            "cpu_limit",
            "memory_usage",
            "memory_limit",
            "http_latency",
            "http_request_count",
            "instance_count",
        ],
        resourceId=resourceId,
        startTime=start_iso,
        endTime=end_iso,
        resolution=max(30, min(300, int(minutes) * 2)),
    )

    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    metrics = metrics if isinstance(metrics, dict) else {}

    def _series_last(m: dict) -> float | None:
        data = (m or {}).get("data")
        if not isinstance(data, list) or not data:
            return None
        try:
            return float(data[-1].get("value"))
        except Exception:
            return None

    def _series_max(m: dict) -> float | None:
        data = (m or {}).get("data")
        if not isinstance(data, list) or not data:
            return None
        vals: list[float] = []
        for pt in data:
            try:
                vals.append(float(pt.get("value")))
            except Exception:
                pass
        return max(vals) if vals else None

    cpu_last = _series_last(metrics.get("cpu_usage", {}))
    cpu_lim_last = _series_last(metrics.get("cpu_limit", {}))
    mem_last = _series_last(metrics.get("memory_usage", {}))
    mem_lim_last = _series_last(metrics.get("memory_limit", {}))

    cpu_pct = (cpu_last / cpu_lim_last * 100.0) if cpu_last is not None and cpu_lim_last else None
    mem_pct = (mem_last / mem_lim_last * 100.0) if mem_last is not None and mem_lim_last else None

    latency_recent_max = _series_max(metrics.get("http_latency", {}))
    req_recent_max = _series_max(metrics.get("http_request_count", {}))
    inst_last = _series_last(metrics.get("instance_count", {}))

    warnings: list[str] = []
    if cpu_pct is not None and cpu_pct >= 85:
        warnings.append(
            f"CPU is high (~{cpu_pct:.0f}% of limit). Consider increasing timeouts or reducing concurrency."
        )
    if mem_pct is not None and mem_pct >= 85:
        warnings.append(
            f"Memory is high (~{mem_pct:.0f}% of limit). Consider reducing parallel work or caching less."
        )
    if latency_recent_max is not None and latency_recent_max >= 2000:
        warnings.append(
            f"HTTP latency is elevated (~{latency_recent_max:.0f}ms recent peak). Expect slower tool calls."
        )

    return {
        "resourceId": payload.get("resourceId"),
        "window_minutes": int(minutes),
        "cpu_usage": cpu_last,
        "cpu_limit": cpu_lim_last,
        "cpu_percent": cpu_pct,
        "memory_usage": mem_last,
        "memory_limit": mem_lim_last,
        "memory_percent": mem_pct,
        "http_latency_recent_max_ms": latency_recent_max,
        "http_requests_recent_max": req_recent_max,
        "instance_count": inst_last,
        "warnings": warnings,
    }
