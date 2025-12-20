from __future__ import annotations

from typing import Any, Callable, Dict, List, Set

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.mcp_server.privacy import strip_location_metadata
from github_mcp.mcp_server.schemas import _strip_internal_meta_fields, _title_from_tool_name


# Tools that should be treated as "high-risk" actions.
#
# Policy:
# - When auto-approve is ON: do not prompt for anything (isConsequential=False).
# - When auto-approve is OFF: prompt only for actions that can change external state.
#
# We treat web browsing and pushing/committing to GitHub as external-state changes.
HIGH_RISK_TOOL_NAMES: Set[str] = {
    # Web browsing
    "web_search",
    "web_fetch",

    # Workspace push-to-GitHub
    "terminal_push",
}

# Tools that create commits via GitHub API (treat like "push/ship-to-GitHub").
# Note: PR creation itself can be non-consequential, but if the tool commits files
# via API it should still be treated as consequential when auto-approve is OFF.
GITHUB_API_COMMIT_TOOL_NAMES: Set[str] = {
    "apply_text_update_and_commit",
    "update_files_and_open_pr",
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

    # Auto-approve toggles whether the connector should prompt for writes.
    auto_approve_on = bool(getattr(server, "AUTO_APPROVE_ENABLED", False))

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
        # - Auto approve ON  => prompt for high-risk (web/push/commit) only
        # - Auto approve OFF => prompt for write tools and any explicitly high-risk tool
        if auto_approve_on:
            is_consequential = bool(high_risk)
        else:
            is_consequential = bool(write_tool or high_risk)

        # Auto-approval is per-action: only consequential actions should ever
        # request confirmation from the UI.
        auto_approved = not bool(is_consequential)

        # Set compatibility metadata fields used by clients.
        meta["auto_approved"] = auto_approved

        # Reflect whether this specific tool mutates state so connectors can
        # render accurate affordances while still allowing everything through.
        meta["write_action"] = bool(write_tool)

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
        meta = _strip_internal_meta_fields(meta)

        schema = _strip_internal_meta_fields(schema)

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
