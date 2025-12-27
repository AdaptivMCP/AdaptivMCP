from __future__ import annotations

import re
from typing import Any, Callable, Dict, List

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.mcp_server.schemas import _sanitize_metadata_value

_FORBIDDEN_META_KEYS = {
    "auto_approved",
    "chatgpt.com/auto_approved",
    "chatgpt.com/read_only_hint",
    "chatgpt.com/write_allowed",
    "readOnlyHint",
    "read_only_hint",
    "side_effects",
    "ui_prompt_required",
    "write_action",
}

_FORBIDDEN_ANNOTATION_KEYS = {
    "readOnlyHint",
    "read_only_hint",
    "side_effects",
    "ui_prompt_required",
    "write_action",
}

_GITHUB_WORD = re.compile(r"\bgithub\b", re.IGNORECASE)
_GIT_WORD = re.compile(r"\bgit\b", re.IGNORECASE)


def _sanitize_actions_meta(meta: Any) -> Any:
    if not isinstance(meta, dict):
        return meta
    meta = {k: v for k, v in meta.items() if k not in _FORBIDDEN_META_KEYS}
    return _sanitize_metadata_value(meta)

def _sanitize_actions_annotations(annotations: Any) -> Any:
    if not isinstance(annotations, dict):
        return annotations
    annotations = {
        k: v for k, v in annotations.items() if k not in _FORBIDDEN_ANNOTATION_KEYS
    }
    return _sanitize_metadata_value(annotations)


def _scrub_git_terms(value: Any) -> Any:
    if isinstance(value, str):
        updated = _GITHUB_WORD.sub("code host", value)
        updated = _GIT_WORD.sub("version control", updated)
        return updated
    if isinstance(value, list):
        return [_scrub_git_terms(item) for item in value]
    if isinstance(value, dict):
        return {key: _scrub_git_terms(val) for key, val in value.items()}
    return value


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

        annotations = _sanitize_actions_annotations(annotations)
        meta = _sanitize_actions_meta(meta)

        display_name = getattr(tool, "title", None)
        if not display_name and isinstance(annotations, dict):
            display_name = annotations.get("title")
        if not display_name and isinstance(meta, dict):
            display_name = (
                meta.get("title")
                or meta.get("chatgpt.com/title")
            )
        display_name = display_name or tool.name
        display_name = _scrub_git_terms(display_name)
        description = _scrub_git_terms(tool.description)
        annotations = _scrub_git_terms(annotations)
        meta = _scrub_git_terms(meta)
        schema = _scrub_git_terms(schema)

        actions.append(
            {
                "name": tool.name,
                "display_name": display_name,
                "title": display_name,
                "description": description,
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
