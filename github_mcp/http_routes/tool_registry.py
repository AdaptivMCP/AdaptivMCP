from __future__ import annotations

import inspect
from typing import Any, Callable, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from github_mcp.server import _find_registered_tool


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _tool_catalog(*, include_parameters: bool, compact: Optional[bool]) -> Dict[str, Any]:
    from github_mcp.main_tools.introspection import list_all_actions

    catalog = list_all_actions(include_parameters=include_parameters, compact=compact)
    tools = list(catalog.get("tools") or [])

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

    return {
        "tools": tools,
        "resources": resources,
        "finite": True,
    }


def _normalize_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict) and "args" in payload:
        args = payload.get("args")
    else:
        args = payload
    if args is None:
        return {}
    if isinstance(args, dict):
        return dict(args)
    if isinstance(args, (list, tuple)):
        normalized: Dict[str, Any] = {}
        for entry in args:
            if isinstance(entry, dict):
                if "name" in entry:
                    normalized[str(entry["name"])] = entry.get("value")
                elif len(entry) == 1:
                    key, value = next(iter(entry.items()))
                    normalized[str(key)] = value
            elif isinstance(entry, (list, tuple)) and len(entry) == 2:
                key, value = entry
                normalized[str(key)] = value
        return normalized
    return {}


async def _invoke_tool(tool_name: str, args: Dict[str, Any]) -> Any:
    resolved = _find_registered_tool(tool_name)
    if not resolved:
        return JSONResponse({"error": f"Unknown tool {tool_name!r}."}, status_code=404)
    _tool, func = resolved
    try:
        result = func(**args)
        if inspect.isawaitable(result):
            result = await result
        return JSONResponse(result if isinstance(result, dict) else {"result": result})
    except Exception as exc:
        from github_mcp.mcp_server.errors import _structured_tool_error

        return JSONResponse(
            _structured_tool_error(exc, context=f"tool_http:{tool_name}"),
            status_code=500,
        )


def build_tool_registry_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        include_parameters = _parse_bool(request.query_params.get("include_parameters")) or False
        compact = _parse_bool(request.query_params.get("compact"))
        return JSONResponse(_tool_catalog(include_parameters=include_parameters, compact=compact))

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
        payload = {}
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        args = _normalize_payload(payload)
        return await _invoke_tool(tool_name, args)

    return _endpoint


def register_tool_registry_routes(app: Any) -> None:
    registry_endpoint = build_tool_registry_endpoint()
    detail_endpoint = build_tool_detail_endpoint()
    invoke_endpoint = build_tool_invoke_endpoint()

    app.add_route("/tools", registry_endpoint, methods=["GET"])
    app.add_route("/resources", registry_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", detail_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", invoke_endpoint, methods=["POST"])
