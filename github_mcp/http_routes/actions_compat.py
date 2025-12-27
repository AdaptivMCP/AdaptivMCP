from __future__ import annotations

from typing import Any, Callable, Dict, List

from starlette.requests import Request
from starlette.responses import JSONResponse

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

        display_name = getattr(tool, "title", None)
        if not display_name and isinstance(annotations, dict):
            display_name = annotations.get("title")
        if not display_name and isinstance(meta, dict):
            display_name = meta.get("title") or meta.get("chatgpt.com/title")
        display_name = display_name or tool.name

        terminal_help = _terminal_help(tool.name, tool.description, schema or {})

        actions.append(
            {
                "name": tool.name,
                "display_name": display_name,
                "title": display_name,
                "description": tool.description,
                "terminal_help": terminal_help,
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
    endpoint = build_actions_endpoint(server)
    app.add_route("/v1/actions", endpoint, methods=["GET"])
    app.add_route("/actions", endpoint, methods=["GET"])
