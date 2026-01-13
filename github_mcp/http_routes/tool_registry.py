from __future__ import annotations

import asyncio
import inspect
import os
import random
from typing import Any, Callable, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from github_mcp.server import _find_registered_tool


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _jitter_sleep_seconds(delay_seconds: float, *, respect_min: bool = True) -> float:
    """Apply jitter to retry sleeps to reduce synchronized backoffs."""

    try:
        delay = float(delay_seconds)
    except Exception:
        return 0.0
    if delay <= 0:
        return 0.0

    # Keep tests deterministic.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return delay

    if respect_min:
        return delay + random.uniform(0.0, min(0.25, delay * 0.25))

    return random.uniform(0.0, delay)


def _tool_catalog(*, include_parameters: bool, compact: Optional[bool]) -> Dict[str, Any]:
    """Build a stable tool/resources catalog for HTTP clients.

 This endpoint is intentionally best-effort: callers use it for discovery.
 If introspection fails (for example during partial startup), return a
 structured error rather than a raw 500 so clients can render a useful
 diagnostic.
 """

    try:
        from github_mcp.main_tools.introspection import list_all_actions

        catalog = list_all_actions(include_parameters=include_parameters, compact=compact)
        tools = list(catalog.get("tools") or [])
        catalog_error: Optional[Dict[str, Any]] = None
    except Exception as exc:
        tools = []
        catalog_error = {
            "message": "Failed to build tool catalog.",
            "type": type(exc).__name__,
        }

    resources = []
    for entry in tools:
        name = entry.get("name")
        if not name:
            continue
        resources.append(
            {
                "uri": f"/tools/{name}",
                "name": name,
                "description": entry.get("description"),
                "mimeType": "application/json",
            }
        )

    payload: Dict[str, Any] = {"tools": tools, "resources": resources, "finite": True}
    if catalog_error is not None:
        payload["error"] = catalog_error
    return payload


def _normalize_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict) and "args" in payload:
        args = payload.get("args")
    else:
        args = payload
    if args is None:
        return {}
    if isinstance(args, dict):
        return {k: v for k, v in args.items() if k != "_meta"}
    if isinstance(args, (list, tuple)):
        normalized: Dict[str, Any] = {}
        for entry in args:
            if isinstance(entry, dict):
                if "name" in entry:
                    name = str(entry["name"])
                    if name == "_meta":
                        continue
                    normalized[name] = entry.get("value")
                elif len(entry) == 1:
                    key, value = next(iter(entry.items()))
                    key_str = str(key)
                    if key_str == "_meta":
                        continue
                    normalized[key_str] = value
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                key, value = entry
                key_str = str(key)
                if key_str == "_meta":
                    continue
                normalized[key_str] = value
        return normalized
    return {}


def _status_code_for_error(error: Dict[str, Any]) -> int:
    """Map structured error payloads to HTTP status codes."""

    code = str(error.get("code") or "")
    category = str(error.get("category") or "")

    if code == "github_rate_limited":
        return 429
    if category == "validation":
        return 400
    if category == "permission":
        return 403
    if category == "not_found":
        return 404
    if category == "conflict":
        return 409
    if category == "timeout":
        return 504
    if category == "upstream":
        return 502

    return 500


def _response_headers_for_error(error: Dict[str, Any]) -> Dict[str, str]:
    details = error.get("details")
    if not isinstance(details, dict):
        return {}

    retry_after = details.get("retry_after_seconds")
    if isinstance(retry_after, (int, float)) and retry_after >= 0:
        return {"Retry-After": str(int(retry_after))}

    return {}


def _is_write_action(tool_obj: Any, func: Any) -> bool:
    value = getattr(func, "__mcp_write_action__", None)
    if value is None:
        value = getattr(tool_obj, "write_action", None)
    return bool(value)


async def _invoke_tool(tool_name: str, args: Dict[str, Any], *, max_attempts: int = 3) -> Response:
    resolved = _find_registered_tool(tool_name)
    if not resolved:
        return JSONResponse({"error": f"Unknown tool {tool_name!r}."}, status_code=404)

    tool_obj, func = resolved
    write_action = _is_write_action(tool_obj, func)

    max_attempts = max(1, int(max_attempts))
    base_backoff_s = 0.25

    attempt = 0
    while True:
        attempt += 1
        try:
            result = func(**args)
            if inspect.isawaitable(result):
                result = await result
            payload = result if isinstance(result, dict) else {"result": result}
            return JSONResponse(payload)
        except Exception as exc:
            from github_mcp.mcp_server.errors import _structured_tool_error

            structured = _structured_tool_error(exc, context=f"tool_http:{tool_name}")
            err = structured.get("error")
            if not isinstance(err, dict):
                err = {}

            retryable = bool(err.get("retryable", False))
            status_code = _status_code_for_error(err)
            headers = _response_headers_for_error(err)

            # Retry only for read tools, and only when explicitly marked retryable.
            if (not write_action) and retryable and attempt < max_attempts:
                delay = min(base_backoff_s * (2 ** (attempt - 1)), 2.0)
                details = err.get("details")
                if isinstance(details, dict):
                    retry_after = details.get("retry_after_seconds")
                    if isinstance(retry_after, (int, float)) and retry_after > 0:
                        delay = min(float(retry_after), 2.0)
                await asyncio.sleep(_jitter_sleep_seconds(delay, respect_min=True))
                continue

            return JSONResponse(structured, status_code=status_code, headers=headers)


def build_tool_registry_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        include_parameters = _parse_bool(request.query_params.get("include_parameters")) or False
        compact = _parse_bool(request.query_params.get("compact"))
        return JSONResponse(_tool_catalog(include_parameters=include_parameters, compact=compact))

    return _endpoint


def build_resources_endpoint() -> Callable[[Request], Response]:
    """Return only the resources list.

 Some clients assume that GET /resources returns a resource list without the
 parallel "tools" field used by GET /tools.
 """

    async def _endpoint(request: Request) -> Response:
        include_parameters = _parse_bool(request.query_params.get("include_parameters")) or False
        compact = _parse_bool(request.query_params.get("compact"))
        catalog = _tool_catalog(include_parameters=include_parameters, compact=compact)
        payload: Dict[str, Any] = {
            "resources": list(catalog.get("resources") or []),
            "finite": True,
        }
        if "error" in catalog:
            payload["error"] = catalog["error"]
        return JSONResponse(payload)

    return _endpoint


def build_tool_detail_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        tool_name = request.path_params.get("tool_name")
        if not tool_name:
            return JSONResponse({"error": "tool_name is required"}, status_code=400)
        catalog = _tool_catalog(include_parameters=True, compact=None)
        tools = [t for t in catalog.get("tools", []) if t.get("name") == tool_name]
        if not tools:
            return JSONResponse({"error": f"Unknown tool {tool_name!r}."}, status_code=404)
        return JSONResponse(tools[0])

    return _endpoint


def build_tool_invoke_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        tool_name = request.path_params.get("tool_name")
        if not tool_name:
            return JSONResponse({"error": "tool_name is required"}, status_code=400)

        try:
            max_attempts = int(request.query_params.get("max_attempts") or "3")
        except Exception:
            max_attempts = 3

        payload: Any = {}
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        args = _normalize_payload(payload)
        return await _invoke_tool(tool_name, args, max_attempts=max_attempts)

    return _endpoint


def register_tool_registry_routes(app: Any) -> None:
    registry_endpoint = build_tool_registry_endpoint()
    resources_endpoint = build_resources_endpoint()
    detail_endpoint = build_tool_detail_endpoint()
    invoke_endpoint = build_tool_invoke_endpoint()

    app.add_route("/tools", registry_endpoint, methods=["GET"])
    app.add_route("/resources", resources_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", detail_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", invoke_endpoint, methods=["POST"])
