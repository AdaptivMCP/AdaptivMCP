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
    return _parse_bool(os.environ.get("WRITE_ALLOWED")) is True


def build_actions_compat_endpoint() -> Callable[[Request], Response]:
    async def _endpoint(request: Request) -> Response:
        # Always include parameters/schemas. ChatGPT needs them for tool calling.
        from github_mcp.main_tools.introspection import list_all_actions

        catalog = list_all_actions(include_parameters=True, compact=None)
        tools = list(catalog.get("tools") or [])

        write_allowed = _get_write_allowed()

        actions = []
        for t in tools:
            name = t.get("name") or ""
            if not name:
                continue

            # Normalize schema keys (some codepaths call it parameters, some inputSchema).
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
                # If meta is some other type, discard it rather than breaking the payload.
                meta = {}

            # Force public visibility for every tool.
            meta["chatgpt.com/visibility"] = "public"

            # Your stated current condition: everything is treated as a write action.
            meta["write_action"] = True
            meta["write_allowed"] = bool(write_allowed)

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


def register_actions_compat_routes(app: Any) -> None:
    endpoint = build_actions_compat_endpoint()
    # Common compatibility routes used by connector clients.
    app.add_route("/v1/actions", endpoint, methods=["GET"])
    app.add_route("/actions", endpoint, methods=["GET"])
