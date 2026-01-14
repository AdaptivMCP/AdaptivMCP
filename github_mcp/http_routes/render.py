from __future__ import annotations

from typing import Any, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from github_mcp.mcp_server.errors import _structured_tool_error


def _parse_int(
    value: Optional[str], *, default: int, min_value: int, max_value: int, name: str
) -> int:
    if value is None:
        return default
    raw = value.strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except Exception as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < min_value:
        return min_value
    if parsed > max_value:
        return max_value
    return parsed


def _parse_str(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _error_response(exc: Exception, *, context: str) -> Response:
    # Reuse the same structured error format + status mapping as /tools.
    from github_mcp.http_routes.tool_registry import (
        _response_headers_for_error,
        _status_code_for_error,
    )

    structured = _structured_tool_error(exc, context=context)

    err = structured.get("error_detail")
    if not isinstance(err, dict):
        raw = structured.get("error")
        err = {"message": raw} if isinstance(raw, str) else {}

    status_code = _status_code_for_error(err)
    headers = _response_headers_for_error(err)
    return JSONResponse(structured, status_code=status_code, headers=headers)


async def _json_body(request: Request) -> Dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def register_render_routes(app: Any) -> None:
    """Register Render API helper endpoints.

    These routes provide an HTTP-first surface for Render operations, built on
    top of the same Render client and tool implementations used by MCP.

    All endpoints return the underlying Render response payload, wrapped with
    status_code/headers/json fields by github_mcp.render_api.render_request.
    """

    async def owners(request: Request) -> Response:
        from github_mcp.main_tools.render import list_render_owners

        cursor = _parse_str(request.query_params.get("cursor"))
        limit = _parse_int(
            request.query_params.get("limit"), default=20, min_value=1, max_value=100, name="limit"
        )
        try:
            result = await list_render_owners(cursor=cursor, limit=limit)
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_owners")

    async def services(request: Request) -> Response:
        from github_mcp.main_tools.render import list_render_services

        owner_id = _parse_str(request.query_params.get("owner_id"))
        cursor = _parse_str(request.query_params.get("cursor"))
        limit = _parse_int(
            request.query_params.get("limit"), default=20, min_value=1, max_value=100, name="limit"
        )
        try:
            result = await list_render_services(owner_id=owner_id, cursor=cursor, limit=limit)
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_services")

    async def service_detail(request: Request) -> Response:
        from github_mcp.main_tools.render import get_render_service

        service_id = str(request.path_params.get("service_id") or "").strip()
        if not service_id:
            return JSONResponse({"error": "service_id is required"}, status_code=400)
        try:
            result = await get_render_service(service_id=service_id)
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_service")

    async def deploys(request: Request) -> Response:
        from github_mcp.main_tools.render import list_render_deploys

        service_id = str(request.path_params.get("service_id") or "").strip()
        if not service_id:
            return JSONResponse({"error": "service_id is required"}, status_code=400)

        cursor = _parse_str(request.query_params.get("cursor"))
        limit = _parse_int(
            request.query_params.get("limit"), default=20, min_value=1, max_value=100, name="limit"
        )
        try:
            result = await list_render_deploys(service_id=service_id, cursor=cursor, limit=limit)
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_deploys")

    async def deploy_detail(request: Request) -> Response:
        from github_mcp.main_tools.render import get_render_deploy

        service_id = str(request.path_params.get("service_id") or "").strip()
        deploy_id = str(request.path_params.get("deploy_id") or "").strip()
        if not service_id or not deploy_id:
            return JSONResponse({"error": "service_id and deploy_id are required"}, status_code=400)
        try:
            result = await get_render_deploy(service_id=service_id, deploy_id=deploy_id)
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_deploy")

    async def deploy_create(request: Request) -> Response:
        from github_mcp.main_tools.render import create_render_deploy

        service_id = str(request.path_params.get("service_id") or "").strip()
        if not service_id:
            return JSONResponse({"error": "service_id is required"}, status_code=400)

        body = await _json_body(request)
        clear_cache = bool(body.get("clear_cache", False))
        commit_id = body.get("commit_id")
        image_url = body.get("image_url")

        try:
            result = await create_render_deploy(
                service_id=service_id,
                clear_cache=clear_cache,
                commit_id=commit_id,
                image_url=image_url,
            )
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_create_deploy")

    async def deploy_cancel(request: Request) -> Response:
        from github_mcp.main_tools.render import cancel_render_deploy

        service_id = str(request.path_params.get("service_id") or "").strip()
        deploy_id = str(request.path_params.get("deploy_id") or "").strip()
        if not service_id or not deploy_id:
            return JSONResponse({"error": "service_id and deploy_id are required"}, status_code=400)
        try:
            result = await cancel_render_deploy(service_id=service_id, deploy_id=deploy_id)
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_cancel_deploy")

    async def deploy_rollback(request: Request) -> Response:
        from github_mcp.main_tools.render import rollback_render_deploy

        service_id = str(request.path_params.get("service_id") or "").strip()
        deploy_id = str(request.path_params.get("deploy_id") or "").strip()
        if not service_id or not deploy_id:
            return JSONResponse({"error": "service_id and deploy_id are required"}, status_code=400)
        try:
            result = await rollback_render_deploy(service_id=service_id, deploy_id=deploy_id)
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_rollback_deploy")

    async def service_restart(request: Request) -> Response:
        from github_mcp.main_tools.render import restart_render_service

        service_id = str(request.path_params.get("service_id") or "").strip()
        if not service_id:
            return JSONResponse({"error": "service_id is required"}, status_code=400)
        try:
            result = await restart_render_service(service_id=service_id)
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_restart_service")

    async def logs(request: Request) -> Response:
        """Fetch logs.

        Preferred shape (Render public API):
          - owner_id (required)
          - resources (one or more ids)

        Legacy shape (kept for back-compat):
          - resource_type + resource_id
        """

        from github_mcp.main_tools.render import get_render_logs, list_render_logs

        owner_id = _parse_str(request.query_params.get("owner_id"))
        start_time = _parse_str(request.query_params.get("start_time"))
        end_time = _parse_str(request.query_params.get("end_time"))
        direction = _parse_str(request.query_params.get("direction")) or "backward"
        limit = _parse_int(
            request.query_params.get("limit"),
            default=200,
            min_value=1,
            max_value=1000,
            name="limit",
        )

        # Accept `resources` as either comma-separated or repeated query params.
        resources: list[str] = []
        try:
            # Starlette's QueryParams supports multi-values.
            resources.extend([r for r in request.query_params.getlist("resources") if r])
            resources.extend([r for r in request.query_params.getlist("resource") if r])
        except Exception:
            pass
        if not resources:
            raw_resources = _parse_str(request.query_params.get("resources"))
            if raw_resources:
                resources = [r.strip() for r in raw_resources.split(",") if r.strip()]
        resources = [r.strip() for r in resources if isinstance(r, str) and r.strip()]

        # Optional filters (best-effort).
        instance = _parse_str(request.query_params.get("instance"))
        host = _parse_str(request.query_params.get("host"))
        level = _parse_str(request.query_params.get("level"))
        method = _parse_str(request.query_params.get("method"))
        path = _parse_str(request.query_params.get("path"))
        text = _parse_str(request.query_params.get("text"))
        log_type = _parse_str(request.query_params.get("log_type"))
        status_code_raw = _parse_str(request.query_params.get("status_code"))
        status_code = None
        if status_code_raw:
            try:
                status_code = int(status_code_raw)
            except Exception:
                return JSONResponse({"error": "status_code must be an integer"}, status_code=400)

        # Preferred path.
        if owner_id and resources:
            try:
                result = await list_render_logs(
                    owner_id=owner_id,
                    resources=resources,
                    start_time=start_time,
                    end_time=end_time,
                    direction=direction,
                    limit=limit,
                    instance=instance,
                    host=host,
                    level=level,
                    method=method,
                    status_code=status_code,
                    path=path,
                    text=text,
                    log_type=log_type,
                )
                return JSONResponse(result)
            except Exception as exc:
                return _error_response(exc, context="http:render_list_logs")

        # Legacy path.
        resource_type = _parse_str(request.query_params.get("resource_type"))
        resource_id = _parse_str(request.query_params.get("resource_id"))
        if not resource_type or not resource_id:
            return JSONResponse(
                {
                    "error": (
                        "Provide either (owner_id + resources) or (resource_type + resource_id). "
                        "Example: /render/logs?owner_id=<id>&resources=srv-..."
                    )
                },
                status_code=400,
            )
        try:
            result = await get_render_logs(
                resource_type=resource_type,
                resource_id=resource_id,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
            return JSONResponse(result)
        except Exception as exc:
            return _error_response(exc, context="http:render_logs")

    app.add_route("/render/owners", owners, methods=["GET"])
    app.add_route("/render/services", services, methods=["GET"])
    app.add_route("/render/services/{service_id:str}", service_detail, methods=["GET"])
    app.add_route("/render/services/{service_id:str}/deploys", deploys, methods=["GET"])
    app.add_route(
        "/render/services/{service_id:str}/deploys/{deploy_id:str}",
        deploy_detail,
        methods=["GET"],
    )
    app.add_route(
        "/render/services/{service_id:str}/deploys",
        deploy_create,
        methods=["POST"],
    )
    app.add_route(
        "/render/services/{service_id:str}/deploys/{deploy_id:str}/cancel",
        deploy_cancel,
        methods=["POST"],
    )
    app.add_route(
        "/render/services/{service_id:str}/deploys/{deploy_id:str}/rollback",
        deploy_rollback,
        methods=["POST"],
    )
    app.add_route(
        "/render/services/{service_id:str}/restart",
        service_restart,
        methods=["POST"],
    )
    app.add_route("/render/logs", logs, methods=["GET"])
