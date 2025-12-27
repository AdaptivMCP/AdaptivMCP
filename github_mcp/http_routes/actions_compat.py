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

# Remove location / device / tracking-ish keys from *anything* we serialize for the UI.
# This does not affect tool execution; it only affects what we emit in schemas/metadata.
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[\W_])("
    r"location|geo|geolocation|lat|latitude|lon|long|longitude|"
    r"device|device_id|fingerprint|"
    r"user[-_]?agent|ua|"
    r"ip|ip_address|remote[-_]?addr|remote[-_]?address|"
    r"x[-_]?forwarded[-_]?for|forwarded|"
    r"timezone|tz|locale"
    r")(?:$|[\W_])",
    re.IGNORECASE,
)


def _strip_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            ks = str(k)
            if _SENSITIVE_KEY_RE.search(ks):
                continue
            out[ks] = _strip_sensitive(v)
        return out
    if isinstance(value, list):
        return [_strip_sensitive(v) for v in value]
    return value


def _sanitize_actions_meta(meta: Any) -> Any:
    if not isinstance(meta, dict):
        return meta
    meta = {k: v for k, v in meta.items() if k not in _FORBIDDEN_META_KEYS}
    meta = _strip_sensitive(meta)
    return _sanitize_metadata_value(meta)


def _sanitize_actions_annotations(annotations: Any) -> Any:
    if not isinstance(annotations, dict):
        return annotations
    annotations = {k: v for k, v in annotations.items() if k not in _FORBIDDEN_ANNOTATION_KEYS}
    annotations = _strip_sensitive(annotations)
    return _sanitize_metadata_value(annotations)


def _terminal_help(name: str, description: str, schema: Any) -> str:
    desc = (description or "").strip()
    synopsis = (desc.splitlines()[0].strip() if desc else "").strip()

    props = {}
    required = set()
    if isinstance(schema, dict):
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])

    lines: List[str] = []
    lines.append(f"NAME")
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
            display_name = meta.get("title") or meta.get("chatgpt.com/title")
        display_name = display_name or tool.name

        # Apply sensitive stripping to schema as well (belt + suspenders).
        schema = _strip_sensitive(schema)

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
    """Register /v1/actions and /actions routes on the ASGI app."""
    endpoint = build_actions_endpoint(server)
    app.add_route("/v1/actions", endpoint, methods=["GET"])
    app.add_route("/actions", endpoint, methods=["GET"])