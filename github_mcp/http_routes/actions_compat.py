from __future__ import annotations

from typing import Any, Callable, Dict, List, Set

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.mcp_server.privacy import strip_location_metadata
from github_mcp.mcp_server.schemas import _title_from_tool_name


# Tools that should be treated as "high-risk" and prompt even when auto-approve is ON.
HIGH_RISK_TOOL_NAMES: Set[str] = {
    # Web browsing
    "web_search",
    "web_fetch",
    # Dedicated push tool
    "terminal_push",
    # If you have other push helpers, add them here as well.
}

# Tools that create commits via GitHub API (treat like "push/ship-to-GitHub").
# Add/adjust names here to match your repo tool surface.
GITHUB_API_COMMIT_TOOL_NAMES: Set[str] = {
    "apply_text_update_and_commit",
    "update_files_and_open_pr",  # if this writes files via API (commit) + opens PR
}


def _tool_tags(tool: Any) -> Set[str]:
    tags = getattr(tool, "tags", None) or []
    out: Set[str] = set()
    for t in tags:
        try:
            out.add(str(t).lower())
        except Exception:
            continue
    return out


def _is_write_tool(tool: Any) -> bool:
    # Primary signal: tool tags include "write"
    tags = _tool_tags(tool)
    if "write" in tags:
        return True

    # Secondary signal: tool meta includes write_action=True (if set by decorator)
    meta = getattr(tool, "meta", None)
    if hasattr(meta, "model_dump"):
        meta = meta.model_dump(exclude_none=True)
    if isinstance(meta, dict) and meta.get("write_action") is True:
        return True

    return False


def _is_high_risk(tool: Any) -> bool:
    name = getattr(tool, "name", "") or ""
    if name in HIGH_RISK_TOOL_NAMES:
        return True
    if name in GITHUB_API_COMMIT_TOOL_NAMES:
        return True
    return False


def serialize_actions_for_compatibility(server: Any) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []

    # In this codebase, server.WRITE_ALLOWED is currently tied to GITHUB_MCP_AUTO_APPROVE.
    auto_approve_on = bool(getattr(server, "WRITE_ALLOWED", False))

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
            meta = {}

        write_tool = _is_write_tool(tool)
        high_risk = _is_high_risk(tool)

        # Consequential policy:
        # - Auto approve ON  => prompt only for high-risk (web/push/github-api-commit)
        # - Auto approve OFF => prompt for ALL write tools + high-risk
        if auto_approve_on:
            is_consequential = high_risk
        else:
            is_consequential = high_risk or write_tool

        # Set compatibility metadata fields used by clients.
        meta["auto_approved"] = auto_approve_on
        meta["write_action"] = bool(is_consequential)
        meta["openai/isConsequential"] = bool(is_consequential)
        meta["x-openai-isConsequential"] = bool(is_consequential)

        if isinstance(annotations, dict):
            annotations["isConsequential"] = bool(is_consequential)
            annotations["readOnlyHint"] = not bool(is_consequential)

        display_name = getattr(tool, "title", None)
        if not display_name and isinstance(annotations, dict):
            display_name = annotations.get("title")
        if not display_name and isinstance(meta, dict):
            display_name = meta.get("title") or meta.get("openai/title")
        display_name = display_name or tool.name
        tool_title = display_name or _title_from_tool_name(tool.name)

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
                "x-openai-isConsequential": bool(is_consequential),
                "isConsequential": bool(is_consequential),
            }
        )

    return actions


def build_actions_endpoint(server: Any) -> Callable[[Request], JSONResponse]:
    async def _endpoint(_: Request) -> JSONResponse:
        return JSONResponse({"actions": serialize_actions_for_compatibility(server)})

    return _endpoint


def register_actions_compat_routes(app: Any, server: Any) -> None:
    endpoint = build_actions_endpoint(server)
    app.add_route("/v1/actions", endpoint, methods=["GET"])
    app.add_route("/actions", endpoint, methods=["GET"])