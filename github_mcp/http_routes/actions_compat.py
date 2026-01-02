from __future__ import annotations

from typing import Any, Callable, Dict, List

from starlette.requests import Request
from starlette.responses import JSONResponse

from github_mcp.mcp_server.context import get_write_allowed

_ALWAYS_WRITE_ENABLED_TOOLS: set[str] = {"authorize_write_actions"}


def _tool_name(tool: Any, func: Any) -> str:
    """Best-effort tool name extraction.

    In most environments `tool` is a framework tool object (e.g., FastMCP Tool)
    with a `.name`. In minimal/test environments it may be the underlying Python
    function.
    """

    name = getattr(tool, "name", None) or getattr(func, "__name__", None) or getattr(tool, "__name__", None)
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


def serialize_actions_for_compatibility(server: Any) -> List[Dict[str, Any]]:
    actions: List[Dict[str, Any]] = []
    write_allowed = bool(get_write_allowed(refresh_after_seconds=0.0))

    for tool, _func in getattr(server, "_REGISTERED_MCP_TOOLS", []):
        tool_name = _tool_name(tool, _func)
        tool_description = _tool_description(tool, _func)
        write_action = _is_write_action(tool, _func)
        write_enabled = (not write_action) or write_allowed or (tool_name in _ALWAYS_WRITE_ENABLED_TOOLS)

        schema = server._normalize_input_schema(tool) or server._normalize_input_schema(_func)

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
        meta_payload = dict(meta or {})
        meta_payload.setdefault("write_action", bool(write_action))
        meta_payload.setdefault("write_enabled", bool(write_enabled))

        display_name = getattr(tool, "title", None)
        if not display_name and isinstance(annotations, dict):
            display_name = annotations.get("title")
        if not display_name and isinstance(meta, dict):
            display_name = meta.get("title") or meta.get("chatgpt.com/title")
        display_name = str(display_name) if display_name else _tool_display_name(tool, _func)

        terminal_help = _terminal_help(tool_name, tool_description, schema or {})

        actions.append(
            {
                "name": tool_name,
                "display_name": display_name,
                "title": display_name,
                "description": tool_description,
                "terminal_help": terminal_help,
                "parameters": schema or {"type": "object", "properties": {}},
                "annotations": annotations,
                "meta": meta_payload,
                "write_action": bool(write_action),
                "write_enabled": bool(write_enabled),
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
