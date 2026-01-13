from __future__ import annotations

from typing import Any, Callable, Dict, List

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.mcp_server.context import get_write_allowed
from github_mcp.mcp_server.schemas import _jsonable
from github_mcp.main_tools.introspection import list_all_actions


def _tool_name(tool: Any, func: Any) -> str:
    """Best-effort tool name extraction.

    In most environments `tool` is a framework tool object (e.g., FastMCP Tool)
    with a `.name`. In minimal/test environments it may be the underlying Python
    function.
    """

    name = (
        getattr(tool, "name", None)
        or getattr(func, "__name__", None)
        or getattr(tool, "__name__", None)
    )
    return str(name or "tool")


def _tool_description(tool: Any, func: Any) -> str:
    """Best-effort tool description extraction."""

    desc = getattr(tool, "description", None)
    if desc:
        return str(desc)

    # Fall back to function docstrings (the MCP decorator sets wrapper.__doc__).
    doc = getattr(func, "__doc__", None) or getattr(tool, "__doc__", None)
    return str(doc or "")


def _tool_display_name(tool: Any, func: Any) -> str:
    """Best-effort human-facing title."""

    title = getattr(tool, "title", None)
    if title:
        return str(title)
    return _tool_name(tool, func)


def _is_write_action(tool: Any, func: Any) -> bool:
    value = getattr(func, "__mcp_write_action__", None)
    if value is None:
        value = getattr(tool, "write_action", None)
    return bool(value)


def _terminal_help(name: str, description: str, schema: Any) -> str:
    desc = (description or "").strip()
    synopsis = (desc.splitlines()[0].strip() if desc else "").strip()

    props = {}
    required = set()
    if isinstance(schema, dict):
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])

    lines: List[str] = []
    lines.append("NAME")
    lines.append(f"  {name}")
    lines.append("")
    lines.append("SYNOPSIS")
    lines.append(f"  {synopsis or '(no synopsis)'}")
    lines.append("")
    lines.append("DESCRIPTION")
    lines.append(f"  {desc or '(no description)'}")
    lines.append("")
    lines.append("PARAMETERS")

    if isinstance(props, dict) and props:
        for param_name in sorted(props.keys()):
            info = props.get(param_name) or {}
            ptype = info.get("type") or "any"
            pdesc = (info.get("description") or "").strip()
            req = " (Required)" if param_name in required else ""
            default = info.get("default", None)
            default_str = f" [default: {default!r}]" if default is not None else ""
            tail = (pdesc + default_str).strip()
            if tail:
                lines.append(f"  -{param_name} <{ptype}>{req}  {tail}")
            else:
                lines.append(f"  -{param_name} <{ptype}>{req}")
    else:
        lines.append("  (none)")

    return "\n".join(lines)


def _strip_is_consequential_metadata(value: Any) -> Any:
    # No-op: do not strip tool metadata.
    return value


def serialize_actions_for_compatibility(server: Any) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    # Keep parity with the main introspection surface.
    # write_actions_enabled indicates whether write actions are auto-approved.
    # Even when auto-approval is off, write tools remain executable (approval-gated).
    write_auto_approved = bool(get_write_allowed(refresh_after_seconds=0.0))
    catalog = list_all_actions(include_parameters=True, compact=False)
    catalog_index = {
        entry.get("name"): entry for entry in (catalog.get("tools") or []) if entry.get("name")
    }

    for tool, _func in getattr(server, "_REGISTERED_MCP_TOOLS", []):
        tool_name = _tool_name(tool, _func)
        catalog_entry = catalog_index.get(tool_name) or {}
        tool_description = catalog_entry.get("description") or _tool_description(tool, _func)
        write_action = bool(catalog_entry.get("write_action", _is_write_action(tool, _func)))
        # Approval-gated writes: keep actions enabled even when write_allowed is false.
        write_enabled = bool(catalog_entry.get("write_enabled", True))
        # Compatibility endpoint: "write_allowed" means the tool can execute.
        # Auto-approval is exposed separately.
        tool_write_allowed = bool(write_enabled)
        approval_required = bool(write_action and not write_auto_approved)

        schema = (
            catalog_entry.get("input_schema")
            or server._normalize_input_schema(tool)
            or server._normalize_input_schema(_func)
        )
        safe_schema = _jsonable(schema or {"type": "object", "properties": {}})
        if not isinstance(safe_schema, dict):
            safe_schema = {"type": "object", "properties": {}}
        visibility = (
            catalog_entry.get("visibility")
            or getattr(_func, "__mcp_visibility__", None)
            or getattr(tool, "__mcp_visibility__", None)
            or "public"
        )

        annotations = getattr(tool, "annotations", None)
        if hasattr(annotations, "model_dump"):
            annotations = annotations.model_dump(exclude_none=True)
        elif not isinstance(annotations, dict):
            annotations = None
        if annotations is not None:
            annotations = _strip_is_consequential_metadata(annotations)

        display_name = getattr(tool, "title", None)
        if not display_name and isinstance(annotations, dict):
            display_name = annotations.get("title")
        display_name = str(display_name) if display_name else _tool_display_name(tool, _func)

        terminal_help = _terminal_help(tool_name, tool_description, safe_schema)

        actions.append(
            {
                "name": tool_name,
                "display_name": display_name,
                "title": display_name,
                "description": tool_description,
                "terminal_help": terminal_help,
                "parameters": safe_schema,
                "annotations": annotations,
                "write_action": bool(write_action),
                "write_allowed": bool(tool_write_allowed),
                "write_auto_approved": bool(write_auto_approved),
                "approval_required": bool(approval_required),
                "write_enabled": bool(write_enabled),
                "visibility": str(visibility),
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
