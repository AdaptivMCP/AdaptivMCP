from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from github_mcp.mcp_server import registry as mcp_registry
from github_mcp.mcp_server.context import REQUEST_CHATGPT_METADATA
from github_mcp.mcp_server.suggestions import (
    augment_structured_error_for_bad_args,
    build_unknown_tool_payload,
)
from github_mcp.server import _find_registered_tool


def _normalize_base_path(base_path: str | None) -> str:
    if not base_path:
        return ""
    cleaned = base_path.strip()
    if cleaned in {"", "/"}:
        return ""
    return "/" + cleaned.strip("/")


def _request_base_path(request: Request, suffixes: Iterable[str]) -> str:
    forwarded_prefix = request.headers.get("x-forwarded-prefix") or request.headers.get(
        "x-forwarded-path"
    )
    if forwarded_prefix:
        return _normalize_base_path(forwarded_prefix)

    path = request.url.path or ""
    for suffix in suffixes:
        if path.endswith(suffix):
            candidate = path[: -len(suffix)]
            return _normalize_base_path(candidate)

    root_path = request.scope.get("root_path") if isinstance(request.scope, dict) else None
    return _normalize_base_path(root_path)


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _jitter_sleep_seconds(delay_seconds: float, *, respect_min: bool = True) -> float:
    """Backward-compatible wrapper for shared retry jitter."""

    from ..retry_utils import jitter_sleep_seconds

    return jitter_sleep_seconds(delay_seconds, respect_min=respect_min, cap_seconds=0.25)


def _tool_catalog(
    *, include_parameters: bool, compact: bool | None, base_path: str = ""
) -> dict[str, Any]:
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
        catalog_error: str | None = None
        catalog_errors = catalog.get("errors")
    except Exception as exc:
        tools = []
        catalog_error = str(exc) or "Failed to build tool catalog."
        catalog_errors = None

    resources = []
    base_path = _normalize_base_path(base_path)
    for entry in tools:
        name = entry.get("name")
        if not name:
            continue
        resources.append(
            {
                "uri": f"{base_path}/tools/{name}",
                "name": name,
                "description": entry.get("description"),
                "mimeType": "application/json",
            }
        )

    payload: dict[str, Any] = {"tools": tools, "resources": resources, "finite": True}
    if catalog_error is not None:
        payload["error"] = catalog_error
    if isinstance(catalog_errors, list) and catalog_errors:
        payload["errors"] = catalog_errors
    return payload


def _coerce_json_args(args: Any) -> Any:
    if not isinstance(args, str):
        return args
    stripped = args.strip()
    if not stripped:
        return args
    if stripped[0] not in {"{", "["}:
        return args
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return args


def _normalize_payload(payload: Any) -> dict[str, Any]:
    """Normalize incoming tool invocation payloads.

    Clients vary in how they wrap arguments. Common shapes include:
      - {"args": {...}} (legacy)
      - {"arguments": {...}} (JSON-RPC/MCP style)
      - {"params": {"arguments": {...}}} (JSON-RPC envelope)
      - {"parameters": {...}} (common LLM client variant)
      - raw dict of arguments

    We normalize to a plain dict of tool kwargs and strip private metadata.
    """

    args: Any = payload
    if isinstance(payload, dict):
        # JSON-RPC envelope: {"id": ..., "params": {"arguments": {...}}}
        params = payload.get("params")
        if isinstance(params, dict):
            if "arguments" in params:
                args = params.get("arguments")
            elif "args" in params:
                args = params.get("args")
            elif "parameters" in params:
                args = params.get("parameters")
            else:
                # Some clients send args directly under params.
                args = params
        elif "arguments" in payload:
            args = payload.get("arguments")
        elif "args" in payload:
            args = payload.get("args")
        elif "parameters" in payload:
            args = payload.get("parameters")
    args = _coerce_json_args(args)
    if args is None:
        return {}
    if isinstance(args, dict):
        return {k: v for k, v in args.items() if k != "_meta"}
    if isinstance(args, (list, tuple)):
        normalized: dict[str, Any] = {}
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


def _default_include_parameters(request: Request) -> bool:
    """Decide whether to include tool schemas by default.

    LLM clients (including ChatGPT-hosted connectors) typically require the
    input schema to reliably invoke tools. When we detect ChatGPT metadata,
    default include_parameters=True even if the query parameter is omitted.
    """

    # Prefer the request-scoped context var, which is set by main.py middleware.
    try:
        if REQUEST_CHATGPT_METADATA.get():
            return True
    except Exception:
        pass

    # Fallback: detect headers directly (in case middleware is disabled).
    try:
        for hdr in (
            "x-openai-assistant-id",
            "x-openai-conversation-id",
            "x-openai-organization-id",
            "x-openai-project-id",
            "x-openai-session-id",
            "x-openai-user-id",
        ):
            if request.headers.get(hdr):
                return True
    except Exception:
        pass

    return False


def _status_code_for_error(error: dict[str, Any]) -> int:
    """Map structured error payloads to HTTP status codes."""

    code = str(error.get("code") or "")
    category = str(error.get("category") or "")

    if code in {"github_rate_limited", "render_rate_limited"} or category == "rate_limited":
        return 429
    if category == "auth":
        return 401
    if category == "validation":
        return 400
    if category == "permission":
        return 403
    if category == "write_approval_required":
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


def _response_headers_for_error(error: dict[str, Any]) -> dict[str, str]:
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
    if value is None:
        meta = getattr(tool_obj, "meta", None)
        if isinstance(meta, dict):
            value = meta.get("write_action")
    return bool(value)


def _effective_write_action(tool_obj: Any, func: Any, args: dict[str, Any]) -> bool:
    """Compute the invocation-level write action classification.

    Tools are registered with a base (inherent) write_action. Some tools (notably
    command runners) can infer read vs write based on the command payload.

    If a resolver exists, it is authoritative for this invocation.
    """

    base = _is_write_action(tool_obj, func)
    resolver = getattr(func, "__mcp_write_action_resolver__", None)
    if callable(resolver):
        try:
            return bool(resolver(args))
        except Exception:
            return bool(base)
    return bool(base)


def _looks_like_structured_error(payload: Any) -> dict[str, Any] | None:
    """Return the error object when payload matches our error shape."""

    if not isinstance(payload, dict):
        return None

    # Newer tools return {"error": "...", "error_detail": {...}}.
    detail = payload.get("error_detail")
    if isinstance(detail, dict) and (
        detail.get("category") or detail.get("code") or detail.get("message")
    ):
        return detail

    err = payload.get("error")
    if isinstance(err, str):
        return {"message": err}
    if not isinstance(err, dict):
        return None
    if not (err.get("category") or err.get("code") or err.get("message")):
        return None
    return err


def _coerce_error_detail(structured: dict[str, Any]) -> dict[str, Any]:
    """Return a dict-like error detail from our structured error envelope."""

    detail = structured.get("error_detail")
    if isinstance(detail, dict):
        return detail

    raw = structured.get("error")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return {"message": raw}
    return {}


@dataclass
class ToolInvocation:
    invocation_id: str
    tool_name: str
    args: dict[str, Any]
    started_at: float
    task: asyncio.Task
    status: str = "running"
    finished_at: float | None = None
    result: Any | None = None
    status_code: int | None = None
    headers: dict[str, str] | None = None


_INVOCATIONS: dict[str, ToolInvocation] = {}
_INVOCATIONS_LOCK = asyncio.Lock()


async def _execute_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    max_attempts: int | None = None,
) -> tuple[Any, int, dict[str, str]]:
    resolved = _find_registered_tool(tool_name)
    if not resolved:
        available: list[str] = []
        try:
            for tool_obj, func in list(getattr(mcp_registry, "_REGISTERED_MCP_TOOLS", []) or []):
                name = mcp_registry._registered_tool_name(tool_obj, func)
                if name:
                    available.append(name)
        except Exception:
            available = []
        payload = build_unknown_tool_payload(tool_name, available)
        return payload, 404, {}

    tool_obj, func = resolved
    write_action = _effective_write_action(tool_obj, func, args)

    try:
        signature: inspect.Signature | None = inspect.signature(func)
    except Exception:
        signature = None

    if max_attempts is not None:
        max_attempts = max(1, int(max_attempts))
    base_backoff_s = 0.25

    attempt = 0
    while True:
        attempt += 1
        try:
            result = func(**args)
            if inspect.isawaitable(result):
                result = await result

            # Some tool wrappers return a structured error payload rather than
            # raising. Translate those into appropriate HTTP status codes so
            # callers can reliably detect failures.
            if isinstance(result, dict):
                err = _looks_like_structured_error(result)
                if err is not None:
                    retryable = bool(err.get("retryable", False))
                    status_code = _status_code_for_error(err)
                    headers = _response_headers_for_error(err)

                    if (
                        (not write_action)
                        and retryable
                        and (max_attempts is None or attempt < max_attempts)
                    ):
                        delay = min(base_backoff_s * (2 ** (attempt - 1)), 2.0)
                        details = err.get("details")
                        if isinstance(details, dict):
                            retry_after = details.get("retry_after_seconds")
                            if isinstance(retry_after, (int, float)) and retry_after > 0:
                                delay = min(float(retry_after), 2.0)
                        await asyncio.sleep(_jitter_sleep_seconds(delay, respect_min=True))
                        continue

                    return result, status_code, headers

            payload = result if isinstance(result, dict) else result
            return payload, 200, {}
        except Exception as exc:
            from github_mcp.mcp_server.error_handling import _structured_tool_error

            structured = _structured_tool_error(
                exc,
                context=f"tool_http:{tool_name}",
                args=args,
            )
            structured = augment_structured_error_for_bad_args(
                structured,
                tool_name=tool_name,
                signature=signature,
                provided_kwargs=args,
                exc=exc,
            )

            # Prefer structured error details when available.
            err = _coerce_error_detail(structured)

            retryable = bool(err.get("retryable", False))
            status_code = _status_code_for_error(err)
            headers = _response_headers_for_error(err)

            # Retry only for read tools, and only when explicitly marked retryable.
            if (
                (not write_action)
                and retryable
                and (max_attempts is None or attempt < max_attempts)
            ):
                delay = min(base_backoff_s * (2 ** (attempt - 1)), 2.0)
                details = err.get("details")
                if isinstance(details, dict):
                    retry_after = details.get("retry_after_seconds")
                    if isinstance(retry_after, (int, float)) and retry_after > 0:
                        delay = min(float(retry_after), 2.0)
                await asyncio.sleep(_jitter_sleep_seconds(delay, respect_min=True))
                continue

            return structured, status_code, headers


def _invocation_payload(invocation: ToolInvocation) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "invocation_id": invocation.invocation_id,
        "tool_name": invocation.tool_name,
        "status": invocation.status,
        "started_at": invocation.started_at,
        "finished_at": invocation.finished_at,
    }
    if invocation.status in {"succeeded", "failed"}:
        payload["result"] = invocation.result
        payload["status_code"] = invocation.status_code
        payload["headers"] = invocation.headers or {}
    return payload


async def _create_invocation(
    tool_name: str, args: dict[str, Any], *, max_attempts: int | None = None
) -> ToolInvocation:
    invocation_id = uuid.uuid4().hex
    task = asyncio.create_task(_execute_tool(tool_name, args, max_attempts=max_attempts))
    invocation = ToolInvocation(
        invocation_id=invocation_id,
        tool_name=tool_name,
        args=args,
        started_at=time.time(),
        task=task,
    )

    async with _INVOCATIONS_LOCK:
        _INVOCATIONS[invocation_id] = invocation

    loop = asyncio.get_running_loop()

    def _finalize(fut: asyncio.Future) -> None:
        async def _update() -> None:
            invocation.finished_at = time.time()
            if fut.cancelled():
                invocation.status = "cancelled"
                return
            try:
                payload, status_code, headers = fut.result()
            except Exception as exc:  # pragma: no cover - defensive
                invocation.status = "failed"
                invocation.result = {"error": str(exc)}
                invocation.status_code = 500
                invocation.headers = {}
                return
            invocation.status_code = int(status_code)
            invocation.headers = dict(headers)
            invocation.result = payload
            invocation.status = "succeeded" if status_code < 400 else "failed"

        loop.create_task(_update())

    task.add_done_callback(_finalize)
    return invocation


async def _get_invocation(invocation_id: str) -> ToolInvocation | None:
    async with _INVOCATIONS_LOCK:
        return _INVOCATIONS.get(invocation_id)


async def _cancel_invocation(invocation: ToolInvocation) -> None:
    if invocation.task.done():
        return
    invocation.status = "cancelling"
    invocation.task.cancel()


async def _invoke_tool(
    tool_name: str, args: dict[str, Any], *, max_attempts: int | None = None
) -> Response:
    payload, status_code, headers = await _execute_tool(
        tool_name,
        args,
        max_attempts=max_attempts,
    )
    return JSONResponse(payload, status_code=status_code, headers=headers)


def build_tool_registry_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        include_parameters = _parse_bool(request.query_params.get("include_parameters"))
        if include_parameters is None:
            include_parameters = _default_include_parameters(request)
        compact = _parse_bool(request.query_params.get("compact"))
        base_path = _request_base_path(request, ("/tools",))
        return JSONResponse(
            _tool_catalog(
                include_parameters=include_parameters,
                compact=compact,
                base_path=base_path,
            )
        )

    return _endpoint


def build_resources_endpoint() -> Callable[[Request], Response]:
    """Return only the resources list.

    Some clients assume that GET /resources returns a resource list without the
    parallel "tools" field used by GET /tools.
    """

    async def _endpoint(request: Request) -> Response:
        include_parameters = _parse_bool(request.query_params.get("include_parameters"))
        if include_parameters is None:
            include_parameters = _default_include_parameters(request)
        compact = _parse_bool(request.query_params.get("compact"))
        base_path = _request_base_path(request, ("/resources",))
        catalog = _tool_catalog(
            include_parameters=include_parameters,
            compact=compact,
            base_path=base_path,
        )
        payload: dict[str, Any] = {
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
            # By default, allow unlimited retries; callers may set max_attempts.
            max_attempts = request.query_params.get("max_attempts")
            if max_attempts is not None:
                max_attempts = int(max_attempts)
        except Exception:
            max_attempts = None

        payload: Any = {}
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        args = _normalize_payload(payload)
        return await _invoke_tool(tool_name, args, max_attempts=max_attempts)

    return _endpoint


def build_tool_invoke_async_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        tool_name = request.path_params.get("tool_name")
        if not tool_name:
            return JSONResponse({"error": "tool_name is required"}, status_code=400)

        try:
            max_attempts = request.query_params.get("max_attempts")
            if max_attempts is not None:
                max_attempts = int(max_attempts)
        except Exception:
            max_attempts = None

        payload: Any = {}
        if request.method in {"POST", "PUT", "PATCH"}:
            try:
                payload = await request.json()
            except Exception:
                payload = {}
        args = _normalize_payload(payload)
        invocation = await _create_invocation(tool_name, args, max_attempts=max_attempts)
        return JSONResponse(_invocation_payload(invocation), status_code=202)

    return _endpoint


def build_tool_invocation_status_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        invocation_id = request.path_params.get("invocation_id")
        if not invocation_id:
            return JSONResponse({"error": "invocation_id is required"}, status_code=400)
        invocation = await _get_invocation(str(invocation_id))
        if invocation is None:
            return JSONResponse({"error": "Unknown invocation id"}, status_code=404)
        return JSONResponse(_invocation_payload(invocation))

    return _endpoint


def build_tool_invocation_cancel_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        invocation_id = request.path_params.get("invocation_id")
        if not invocation_id:
            return JSONResponse({"error": "invocation_id is required"}, status_code=400)
        invocation = await _get_invocation(str(invocation_id))
        if invocation is None:
            return JSONResponse({"error": "Unknown invocation id"}, status_code=404)
        await _cancel_invocation(invocation)
        return JSONResponse(_invocation_payload(invocation))

    return _endpoint


def register_tool_registry_routes(app: Any) -> None:
    registry_endpoint = build_tool_registry_endpoint()
    resources_endpoint = build_resources_endpoint()
    detail_endpoint = build_tool_detail_endpoint()
    invoke_endpoint = build_tool_invoke_endpoint()
    invoke_async_endpoint = build_tool_invoke_async_endpoint()
    invocation_status_endpoint = build_tool_invocation_status_endpoint()
    invocation_cancel_endpoint = build_tool_invocation_cancel_endpoint()

    app.add_route("/tools", registry_endpoint, methods=["GET"])
    app.add_route("/resources", resources_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", detail_endpoint, methods=["GET"])
    app.add_route("/tools/{tool_name:str}", invoke_endpoint, methods=["POST"])
    app.add_route("/tools/{tool_name:str}/invocations", invoke_async_endpoint, methods=["POST"])
    app.add_route(
        "/tool_invocations/{invocation_id:str}",
        invocation_status_endpoint,
        methods=["GET"],
    )
    app.add_route(
        "/tool_invocations/{invocation_id:str}/cancel",
        invocation_cancel_endpoint,
        methods=["POST"],
    )
    _prioritize_tool_registry_routes(
        app,
        [
            registry_endpoint,
            resources_endpoint,
            detail_endpoint,
            invoke_endpoint,
            invoke_async_endpoint,
            invocation_status_endpoint,
            invocation_cancel_endpoint,
        ],
    )


def _prioritize_tool_registry_routes(app: Any, endpoints: Iterable[Callable[..., Any]]) -> None:
    """Move tool registry routes to the front of the routing table."""

    router = getattr(app, "router", None)
    routes = getattr(router, "routes", None)
    if not isinstance(routes, list):
        return

    endpoint_set = {endpoint for endpoint in endpoints if callable(endpoint)}
    if not endpoint_set:
        return

    prioritized = []
    remaining = []
    for route in routes:
        endpoint = getattr(route, "endpoint", None)
        if endpoint in endpoint_set:
            prioritized.append(route)
        else:
            remaining.append(route)

    if prioritized:
        router.routes = prioritized + remaining
