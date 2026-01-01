from __future__ import annotations

import asyncio
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


def _attach_meta(payload: Dict[str, Any], *, tool: str, attempts: int, write_action: bool, max_attempts: int) -> None:
    """Attach _meta without breaking existing result payloads."""

    meta = payload.get("_meta")
    if not isinstance(meta, dict):
        meta = {}
        payload["_meta"] = meta

    meta.setdefault("tool", tool)
    meta.setdefault("attempts", int(attempts))
    meta.setdefault("max_attempts", int(max_attempts))
    meta.setdefault("write_action", bool(write_action))


async def _preflight_validate(tool_name: str, args: Dict[str, Any]) -> Optional[JSONResponse]:
    """Validate args against the published schema without running the tool.

    This prevents raw TypeErrors (e.g., unexpected kwargs) from bubbling up as 500s.

    Returns a JSONResponse when invalid; None when valid or when preflight failed.
    """

    try:
        from github_mcp.main_tools.introspection import validate_tool_args
        from github_mcp.mcp_server.errors import AdaptivToolError, _structured_tool_error

        result = await validate_tool_args(tool_name=tool_name, payload=args)
        valid = bool(result.get("valid", True))
        if valid:
            return None

        err = AdaptivToolError(
            code="tool_args_invalid",
            message=f"Tool arguments did not match schema for {tool_name!r}.",
            category="validation",
            origin="schema",
            retryable=False,
            details={
                "tool": tool_name,
                "errors": result.get("errors") or [],
            },
            hint="Fetch the tool schema (/tools/<name> or describe_tool) and resend args exactly.",
        )
        payload = _structured_tool_error(err, context=f"tool_http:{tool_name}")
        return JSONResponse(payload, status_code=400)
    except ValueError:
        return JSONResponse({"error": f"Unknown tool {tool_name!r}."}, status_code=404)
    except Exception:
        # Best-effort only; fall back to tool's own validation if this fails.
        return None


async def _invoke_tool(tool_name: str, args: Dict[str, Any], *, max_attempts: int = 3) -> Response:
    resolved = _find_registered_tool(tool_name)
    if not resolved:
        return JSONResponse({"error": f"Unknown tool {tool_name!r}."}, status_code=404)

    tool_obj, func = resolved
    write_action = _is_write_action(tool_obj, func)

    preflight = await _preflight_validate(tool_name, args)
    if preflight is not None:
        return preflight

    max_attempts = max(1, min(int(max_attempts), 5))
    base_backoff_s = 0.25

    attempt = 0
    while True:
        attempt += 1
        try:
            result = func(**args)
            if inspect.isawaitable(result):
                result = await result
            payload = result if isinstance(result, dict) else {"result": result}
            if isinstance(payload, dict):
                _attach_meta(
                    payload,
                    tool=tool_name,
                    attempts=attempt,
                    write_action=write_action,
                    max_attempts=max_attempts,
                )
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
                await asyncio.sleep(delay)
                continue

            if isinstance(structured, dict):
                _attach_meta(
                    structured,
                    tool=tool_name,
                    attempts=attempt,
                    write_action=write_action,
                    max_attempts=max_attempts,
                )
            return JSONResponse(structured, status_code=status_code, headers=headers)


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
    detail_endpoint = build_tool_detail_endpoint()
    invoke_endpoint = build_tool_invoke_endpoint()

    app.add_route("/tools", registry_endpoint, methods=["GET"])
    app.add_route("/resources", registry_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", detail_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", invoke_endpoint, methods=["POST"])
