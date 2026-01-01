from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _get_write_allowed() -> bool:
    # Dynamic at request time (no import-time caching).
    # Prefer MCP_WRITE_ALLOWED if present, otherwise fall back to WRITE_ALLOWED.
    v = os.environ.get("MCP_WRITE_ALLOWED")
    if v is None:
        v = os.environ.get("WRITE_ALLOWED")
    return _parse_bool(v) is True


def build_actions_compat_endpoint(*, server: Any = None) -> Callable[[Request], Response]:
    """
    server is accepted for compatibility with older main.py call sites.
    It is intentionally unused here.
    """
    async def _endpoint(request: Request) -> Response:
        # Always include parameters/schemas. Clients need them for tool calling.
        from github_mcp.main_tools.introspection import list_all_actions

        catalog = list_all_actions(include_parameters=True, compact=None)
        tools = list(catalog.get("tools") or [])

        write_allowed = _get_write_allowed()

        actions = []
        for t in tools:
            name = t.get("name") or ""
            if not name:
                continue

            # Normalize schema key(s).
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

            # Force public visibility for every tool.
            meta["chatgpt.com/visibility"] = "public"
            meta["visibility"] = "public"

            # Per your current condition: everything is treated as write action.
            meta["write_action"] = True
            meta["write_allowed"] = bool(write_allowed)
            meta["write_enabled"] = bool(write_allowed)

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
    """
    Backward compatible signature: main.py/tests may pass (app, server).
    """
    endpoint = build_actions_compat_endpoint(server=server)
    app.add_route("/v1/actions", endpoint, methods=["GET"])
    app.add_route("/actions", endpoint, methods=["GET"])