from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from github_mcp.render_api import render_request


def _require_non_empty_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _normalize_optional_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    cleaned = value.strip()
    return cleaned or None


def _normalize_limit(
    limit: Any,
    *,
    default: int,
    min_value: int,
    max_value: int,
    name: str = "limit",
) -> int:
    if limit is None:
        return default
    if isinstance(limit, bool):
        raise TypeError(f"{name} must be an integer")
    if isinstance(limit, str):
        limit = limit.strip()
        if limit.isdigit():
            limit = int(limit)
    if not isinstance(limit, int):
        raise TypeError(f"{name} must be an integer")
    if limit < min_value:
        return min_value
    if limit > max_value:
        return max_value
    return limit


def _parse_iso8601(ts: str, *, name: str) -> datetime:
    """Parse a best-effort ISO8601 timestamp.

    Accepts:
    - RFC3339 / ISO8601 strings, with or without timezone
    - A trailing "Z" (treated as UTC)

    Raises ValueError when parsing fails.
    """

    if not isinstance(ts, str) or not ts.strip():
        raise ValueError(f"{name} must be a non-empty ISO8601 timestamp")
    raw = ts.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception as exc:
        raise ValueError(
            f"{name} must be an ISO8601 timestamp (example: 2026-01-14T12:34:56Z)"
        ) from exc

    # Make naive datetimes explicit UTC for downstream comparisons.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_iso8601(ts: Optional[str], *, name: str) -> Optional[str]:
    if ts is None:
        return None
    parsed = _parse_iso8601(ts, name=name)
    # Emit RFC3339 with "Z" when UTC.
    if parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed):
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return parsed.isoformat()


async def list_render_owners(cursor: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """List Render owners (workspaces + personal owners).

    Render's API exposes workspaces via the "owners" collection.

    Args:
      cursor: Optional pagination cursor from a previous response.
      limit: Page size (clamped to [1, 100]).
    """

    params: Dict[str, Any] = {
        "limit": _normalize_limit(limit, default=20, min_value=1, max_value=100)
    }
    cursor = _normalize_optional_str(cursor)
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

    Args:
      owner_id: Optional Render owner/workspace id.
      cursor: Optional pagination cursor from a previous response.
      limit: Page size (clamped to [1, 100]).
    """

    params: Dict[str, Any] = {
        "limit": _normalize_limit(limit, default=20, min_value=1, max_value=100)
    }
    cursor = _normalize_optional_str(cursor)
    if cursor:
        params["cursor"] = cursor
    owner_id = _normalize_optional_str(owner_id)
    if owner_id:
        params["ownerId"] = owner_id
    return await render_request("GET", "/services", params=params)


async def get_render_service(service_id: str) -> Dict[str, Any]:
    """Fetch a single Render service by id."""

    service_id = _require_non_empty_str("service_id", service_id)
    return await render_request("GET", f"/services/{service_id}")


async def list_render_deploys(
    service_id: str,
    cursor: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """List deploys for a Render service.

    Args:
      service_id: Render service id.
      cursor: Optional pagination cursor.
      limit: Page size (clamped to [1, 100]).
    """

    service_id = _require_non_empty_str("service_id", service_id)
    params: Dict[str, Any] = {
        "limit": _normalize_limit(limit, default=20, min_value=1, max_value=100)
    }
    cursor = _normalize_optional_str(cursor)
    if cursor:
        params["cursor"] = cursor
    return await render_request("GET", f"/services/{service_id}/deploys", params=params)


async def get_render_deploy(service_id: str, deploy_id: str) -> Dict[str, Any]:
    """Fetch a specific deploy for a Render service."""

    service_id = _require_non_empty_str("service_id", service_id)
    deploy_id = _require_non_empty_str("deploy_id", deploy_id)
    return await render_request("GET", f"/services/{service_id}/deploys/{deploy_id}")


async def create_render_deploy(
    service_id: str,
    clear_cache: bool = False,
    commit_id: Optional[str] = None,
    image_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Trigger a new deploy for a Render service.

    You may optionally set one of:
    - commit_id: Git commit SHA to deploy (for repo-backed services)
    - image_url: Container image URL (for image-backed services)

    Passing both commit_id and image_url is invalid.
    """

    service_id = _require_non_empty_str("service_id", service_id)
    commit_id = _normalize_optional_str(commit_id)
    image_url = _normalize_optional_str(image_url)

    if commit_id and image_url:
        raise ValueError("Provide only one of commit_id or image_url")

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

    service_id = _require_non_empty_str("service_id", service_id)
    deploy_id = _require_non_empty_str("deploy_id", deploy_id)

    return await render_request(
        "POST",
        f"/services/{service_id}/deploys/{deploy_id}/cancel",
    )


async def rollback_render_deploy(service_id: str, deploy_id: str) -> Dict[str, Any]:
    """Roll back a service to a previous deploy."""

    service_id = _require_non_empty_str("service_id", service_id)
    deploy_id = _require_non_empty_str("deploy_id", deploy_id)

    return await render_request(
        "POST",
        f"/services/{service_id}/deploys/{deploy_id}/rollback",
    )


async def restart_render_service(service_id: str) -> Dict[str, Any]:
    """Restart a running service."""

    service_id = _require_non_empty_str("service_id", service_id)
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

    Render's logs endpoint supports resourceType/resourceId plus optional time bounds.

    Args:
      resource_type: "service" or "job".
      resource_id: Resource id corresponding to the type.
      start_time/end_time: ISO8601 timestamps (examples: 2026-01-14T12:34:56Z).
      limit: Max log lines to return (clamped to [1, 1000]).
    """

    resource_type = _require_non_empty_str("resource_type", resource_type).lower()
    if resource_type not in {"service", "job"}:
        raise ValueError("resource_type must be one of: service, job")
    resource_id = _require_non_empty_str("resource_id", resource_id)

    start_norm = _normalize_iso8601(start_time, name="start_time")
    end_norm = _normalize_iso8601(end_time, name="end_time")

    if start_norm and end_norm:
        start_dt = _parse_iso8601(start_norm, name="start_time")
        end_dt = _parse_iso8601(end_norm, name="end_time")
        if start_dt > end_dt:
            raise ValueError("start_time must be <= end_time")

    params: Dict[str, Any] = {
        "resourceType": resource_type,
        "resourceId": resource_id,
        "limit": _normalize_limit(limit, default=200, min_value=1, max_value=1000),
    }
    if start_norm:
        params["startTime"] = start_norm
    if end_norm:
        params["endTime"] = end_norm

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
