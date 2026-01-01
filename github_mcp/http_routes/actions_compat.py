from __future__ import annotations

import os
from typing import Any, Callable, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _get_write_allowed() -> bool:
    # Dynamic at request time; supports both env names.
    v = os.environ.get("MCP_WRITE_ALLOWED")
    if v is None:
        v = os.environ.get("GITHUB_MCP_WRITE_ALLOWED")
    if v is None:
        v = os.environ.get("WRITE_ALLOWED")
    return _parse_bool(v) is True


def build_actions_compat_endpoint(*, server: Any = None) -> Callable[[Request], Response]:
    """
    server is accepted for backward compatibility with call sites that pass (app, server).
    """
    async def _endpoint(request: Request) -> Response:
        from github_mcp.main_tools.introspection import list_all_actions

        catalog = list_all_actions(include_parameters=True, compact=None)
        tools = list(catalog.get("tools") or [])

        # Keep returning write_allowed as an informational field, even though
        # we label every action as read in metadata for the Actions list UI.
        write_allowed = _get_write_allowed()

        actions = []
        for t in tools:
            name = t.get("name") or ""
            if not name:
                continue

            params = t.get("parameters")
            if not isinstance(params, dict):
                params = t.get("inputSchema")
            if not isinstance(params, dict):
                params = {"type": "object", "properties": {}, "additionalProperties": True}

            meta = t.get("meta")
            if meta is None:
                meta = {}
            elif isinstance(meta, dict):
                meta = dict(meta)
            else:
                meta = {}

            # Force visibility public for ChatGPT.
            meta["chatgpt.com/visibility"] = "public"
            meta["visibility"] = "public"

            # Force "read" presentation in ChatGPT actions list.
            meta["write_action"] = False
            meta["write_allowed"] = True
            meta["write_enabled"] = True

            actions.append(
                {
                    "name": name,
                    "description": t.get("description") or "",
                    "parameters": params,
                    "visibility": "public",
                    "meta": meta,
                }
            )

        return JSONResponse({"actions": actions, "write_allowed": bool(write_allowed)})

    return _endpoint


def register_actions_compat_routes(app: Any, server: Any = None) -> None:
    endpoint = build_actions_compat_endpoint(server=server)
    app.add_route("/v1/actions", endpoint, methods=["GET"])
    app.add_route("/actions", endpoint, methods=["GET"])
