"""GitHub Actions compatibility routes (for legacy clients).

HTTP routes exposed alongside MCP (healthz, compat endpoints).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.mcp_server.privacy import strip_location_metadata

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
        elif isinstance(meta, dict):
            meta = dict(meta)
        else:
            meta = None

        if meta is None:
            meta = {}

        if isinstance(meta, dict) and getattr(server, "WRITE_ALLOWED", False):
            meta["auto_approved"] = True
            meta["openai/isConsequential"] = False
            meta["x-openai-isConsequential"] = False

        display_name = getattr(tool, "title", None)
        if not display_name and isinstance(annotations, dict):
            display_name = annotations.get("title")
        if not display_name and isinstance(meta, dict):
            display_name = meta.get("title") or meta.get("openai/title")
        display_name = display_name or tool.name
        tool_title = display_name or _title_from_tool_name(tool.name)

        is_consequential = None
        if isinstance(meta, dict):
            is_consequential = meta.get("x-openai-isConsequential")
            if is_consequential is None:
                is_consequential = meta.get("openai/isConsequential")
        if is_consequential is None and isinstance(annotations, dict):
            is_consequential = annotations.get("isConsequential")

        if getattr(server, "WRITE_ALLOWED", False):
            is_consequential = False
            if isinstance(annotations, dict):
                annotations["isConsequential"] = False
        elif is_consequential is not None:
            is_consequential = bool(is_consequential)

        # Ensure compatibility metadata is present even when compact metadata is
        # enabled at registration time.
        meta.setdefault("openai/visibility", meta.get("visibility", "public"))
        meta.setdefault("visibility", meta.get("openai/visibility", "public"))
        meta.setdefault("openai/toolInvocation/invoking", f"Adaptiv: {tool_title}")
        meta.setdefault("openai/toolInvocation/invoked", f"Adaptiv: {tool_title} done")
        meta = strip_location_metadata(meta)

        actions.append(
            {
                "name": tool.name,
                "display_name": display_name,
                "title": display_name,
                "description": tool.description,
                "parameters": schema or {"type": "object", "properties": {}},
                "annotations": annotations,
                "meta": meta,
                "x-openai-isConsequential": is_consequential,
                "isConsequential": is_consequential,
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
from github_mcp.mcp_server.schemas import _title_from_tool_name
