from __future__ import annotations

from typing import Any, Callable, Dict, List

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.mcp_server.schemas import _sanitize_metadata_value

_FORBIDDEN_META_KEYS = {
    "auto_approved",
    "openai/auto_approved",
    "chatgpt.com/auto_approved",
}


def _sanitize_actions_meta(meta: Any) -> Any:
    if not isinstance(meta, dict):
        return meta
    meta = {k: v for k, v in meta.items() if k not in _FORBIDDEN_META_KEYS}
    return _sanitize_metadata_value(meta)


def serialize_actions_for_compatibility(server: Any) -> List[Dict[str, Any]]:
    """Expose a stable actions listing for clients expecting /v1/actions.

    The FastMCP server only exposes its MCP transport at ``/mcp`` by default.
    Some clients (including the ChatGPT UI) attempt to refresh available actions
    using the OpenAI Actions-style ``/v1/actions`` endpoint. This produces a
    lightweight JSON response that mirrors the MCP tool surface.
    """

    actions: List[Dict[str, Any]] = []
    for tool, _func in getattr(server, "_REGISTERED_MCP_TOOLS", []):
        schema = server._normalize_input_schema(tool)

        annotations = getattr(tool, "annotations", None)
        if hasattr(annotations, "model_dump"):
            annotations = annotations.model_dump(exclude_none=True)
        elif not isinstance(annotations, dict):
            annotations = None

        meta = getattr(tool, "meta", None)
        if hasattr(meta, "model_dump"):
            meta = meta.model_dump(exclude_none=True)
        elif not isinstance(meta, dict):
            meta = None

        annotations = _sanitize_metadata_value(annotations)
        meta = _sanitize_actions_meta(meta)

        display_name = getattr(tool, "title", None)
        if not display_name and isinstance(annotations, dict):
            display_name = annotations.get("title")
        if not display_name and isinstance(meta, dict):
            display_name = (
                meta.get("title")
                or meta.get("openai/title")
                or meta.get("chatgpt.com/title")
            )
        display_name = display_name or tool.name

        actions.append(
            {
                "name": tool.name,
                "display_name": display_name,
                "title": display_name,
                "description": tool.description,
                "parameters": schema or {"type": "object", "properties": {}},
                "annotations": annotations,
                "meta": meta,
            }
        )

    return actions


def build_actions_endpoint(server: Any) -> Callable[[Request], JSONResponse]:
    async def _endpoint(_: Request) -> JSONResponse:
        return JSONResponse({"actions": serialize_actions_for_compatibility(server)})

    return _endpoint


def register_actions_compat_routes(app: Any, server: Any) -> None:
    """Register /v1/actions and /actions routes on the ASGI app."""

    endpoint = build_actions_endpoint(server)
    app.add_route("/v1/actions", endpoint, methods=["GET"])
    app.add_route("/actions", endpoint, methods=["GET"])
