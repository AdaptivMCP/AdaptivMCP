from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from github_mcp.mcp_server.context import get_auto_approve_enabled
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS, _registered_tool_name
from github_mcp.mcp_server.schemas import _schema_for_callable

from ._main import _main


def list_write_tools() -> dict[str, Any]:
    """Describe write-capable tools exposed by this server.

    This is a lightweight summary that avoids scanning the full module.
    """
    catalog = list_all_actions(include_parameters=False, compact=True)
    tools: list[dict[str, Any]] = []
    for entry in catalog.get("tools", []) or []:
        if not entry.get("write_action"):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        tools.append(
            {
                "name": name,
                "category": _write_tool_category(name, entry),
                "description": _clean_description(entry.get("description") or ""),
            }
        )
    tools.sort(key=lambda t: t["name"])
    return {"tools": tools}


def _tool_attr(tool: Any, func: Any, name: str, default: Any = None) -> Any:
    """Best-effort attribute resolution across tool and function wrappers."""

    private = f"__mcp_{name}__"
    if hasattr(func, private):
        return getattr(func, private)
    if hasattr(tool, name):
        return getattr(tool, name)
    return default


def _tool_tags(tool: Any, func: Any) -> list[str]:
    """Return tags for a tool."""

    tags = getattr(func, "__mcp_tags__", None)
    if isinstance(tags, (list, tuple)):
        return [str(t) for t in tags if t is not None and str(t).strip()]

    meta = getattr(tool, "meta", None)
    if isinstance(meta, dict):
        mtags = meta.get("tags")
        if isinstance(mtags, (list, tuple)):
            return [str(t) for t in mtags if t is not None and str(t).strip()]

    return []


def _tool_ui(tool: Any, func: Any) -> dict[str, Any] | None:
    """Return UI metadata for a tool."""

    ui = getattr(func, "__mcp_ui__", None)
    if isinstance(ui, Mapping):
        return dict(ui)

    meta = getattr(tool, "meta", None)
    if isinstance(meta, dict):
        ui = meta.get("ui")
        if isinstance(ui, dict):
            return dict(ui)

    return None


def _clean_description(text: str) -> str:
    if not text:
        return text
    return str(text).strip()


def _write_tool_category(name: str, entry: Mapping[str, Any]) -> str:
    ui = entry.get("ui")
    ui_group = None
    if isinstance(ui, Mapping):
        group = ui.get("group")
        if isinstance(group, str) and group.strip():
            ui_group = group.strip()
            if ui_group != "github":
                return ui_group

    lowered = name.lower()
    if "workflow" in lowered:
        return "workflow"
    if "issue" in lowered:
        return "issue"
    if "pull_request" in lowered or lowered.startswith("pr_") or "_pr_" in lowered:
        return "pr"
    if "branch" in lowered:
        return "branch"
    if (
        "workspace" in lowered
        or lowered in {"apply_patch", "run_tests", "run_python", "terminal_command"}
        or lowered.startswith(("apply_workspace", "commit_workspace", "move_workspace"))
    ):
        return "workspace"

    return ui_group or "github"


def _write_gate_state() -> dict[str, bool]:
    auto_approved = bool(get_auto_approve_enabled())
    return {
        "write_auto_approved": auto_approved,
        "write_actions_enabled": True,
        "write_enabled": True,
        "write_allowed": auto_approved,
    }


def _approval_required(write_action: bool, write_auto_approved: bool) -> bool:
    return bool(write_action) and not bool(write_auto_approved)


def _tool_registry() -> list[tuple[Any, Any]]:
    m = _main()
    registry = getattr(m, "_REGISTERED_MCP_TOOLS", None)
    if isinstance(registry, list):
        return registry
    return _REGISTERED_MCP_TOOLS


def _iter_tool_registry() -> tuple[list[tuple[Any, Any]], list[dict[str, Any]]]:
    """Return validated registry entries plus structured errors."""

    entries: list[tuple[Any, Any]] = []
    errors: list[dict[str, Any]] = []

    registry = _tool_registry()
    try:
        iterator = iter(registry)
    except TypeError as exc:
        errors.append(
            {
                "error": "tool registry is not iterable",
                "details": str(exc),
            }
        )
        return entries, errors

    for idx, entry in enumerate(iterator):
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            errors.append(
                {
                    "entry_index": idx,
                    "error": "registry entry is not a (tool, func) pair",
                    "details": str(type(entry)),
                }
            )
            continue
        tool, func = entry
        name = _registered_tool_name(tool, func)
        if not callable(func):
            errors.append(
                {
                    "entry_index": idx,
                    "name": name,
                    "error": "registry entry callable is missing or not callable",
                }
            )
            continue
        if not name:
            errors.append(
                {
                    "entry_index": idx,
                    "error": "registry entry missing tool name",
                }
            )
            continue
        entries.append((tool, func))

    return entries, errors


def list_all_actions(
    include_parameters: bool = False, compact: bool | None = None
) -> dict[str, Any]:
    """Enumerate every available MCP tool with optional schemas.

    Canonical “schema registry” used by clients.
    - Inherent tool classification is always reported as write_action (True/False).
    """

    m = _main()
    compact_mode = m.COMPACT_METADATA_DEFAULT if compact is None else compact

    tools: list[dict[str, Any]] = []
    gate = _write_gate_state()
    write_auto_approved = gate["write_auto_approved"]
    seen_names: set[str] = set()
    registry_entries, registry_errors = _iter_tool_registry()

    # Always include the introspection endpoints even if the tool registry is
    # monkeypatched (tests rely on these being present so the server can still
    # describe itself when the registry is incomplete).
    from types import SimpleNamespace

    forced_entries = [
        (SimpleNamespace(name="list_all_actions", write_action=False), list_all_actions),
        (SimpleNamespace(name="list_tools", write_action=False), list_tools),
        (SimpleNamespace(name="list_resources", write_action=False), list_resources),
        (SimpleNamespace(name="list_write_actions", write_action=False), list_write_actions),
        (SimpleNamespace(name="list_write_tools", write_action=False), list_write_tools),
    ]

    for tool, func in forced_entries + list(registry_entries):
        name = _registered_tool_name(tool, func)
        if not name:
            continue
        name_str = str(name)
        if name_str in seen_names:
            continue
        seen_names.add(name_str)

        description = getattr(tool, "description", None) or (func.__doc__ or "")
        description = description.strip()
        description = _clean_description(description)

        if not compact_mode:
            full_doc = (func.__doc__ or "").strip()
            if full_doc and len(full_doc) > len(description):
                description = full_doc

        # Compact mode: keep only first line, but do NOT truncate characters.
        if compact_mode and description:
            description = description.splitlines()[0].strip() or description

        visibility = (
            getattr(func, "__mcp_visibility__", None)
            or getattr(tool, "__mcp_visibility__", None)
            or "public"
        )

        base_write_action = bool(_tool_attr(tool, func, "write_action", False))
        approval_required = _approval_required(base_write_action, write_auto_approved)
        tool_info: dict[str, Any] = {
            "name": name_str,
            "visibility": str(visibility),
            # Correct semantic classification:
            "write_action": base_write_action,
            "tags": _tool_tags(tool, func),
            "write_allowed": gate["write_allowed"],
            "write_enabled": gate["write_enabled"],
            "write_auto_approved": write_auto_approved,
            "write_actions_enabled": gate["write_actions_enabled"],
            "approval_required": approval_required,
        }

        # UI presentation hints.
        ann = getattr(tool, "annotations", None)
        if isinstance(ann, dict) and ann:
            tool_info["annotations"] = ann

        ui_meta = _tool_ui(tool, func)
        if isinstance(ui_meta, Mapping) and ui_meta:
            tool_info["ui"] = ui_meta

        # Convenience fields for UIs that want stable text labels.
        if "ui" in tool_info and isinstance(tool_info.get("ui"), dict):
            ui2 = tool_info["ui"]
            inv = ui2.get("invoking")
            done = ui2.get("invoked")
            if isinstance(inv, str) and inv.strip():
                tool_info["invoking_message"] = inv.strip()
            if isinstance(done, str) and done.strip():
                tool_info["invoked_message"] = done.strip()

        if description:
            tool_info["description"] = description

        # Tool classification is expressed via write_action plus the gating fields.

        if include_parameters:
            # IMPORTANT: compute schemas dynamically from the live callable.
            #
            # Many downstream clients treat input schemas as a hard contract.
            # When running in dev environments (hot reload / editable installs)
            # the decorator-attached schema can become stale if the underlying
            # signature changes. Prefer recomputing from the current signature
            # each time the catalog is requested.
            safe_schema = _schema_for_callable(func, tool, tool_name=name_str)
            # Compatibility: some MCP clients and UIs expect `inputSchema`
            # (camelCase) per the MCP tool schema convention.
            tool_info["input_schema"] = safe_schema
            tool_info["inputSchema"] = safe_schema

        tools.append(tool_info)

    tools.sort(key=lambda entry: entry["name"])

    payload: dict[str, Any] = {
        "compact": compact_mode,
        "tools": tools,
    }

    if isinstance(registry_errors, list) and registry_errors:
        payload["errors"] = registry_errors
    return payload


def list_write_actions(
    include_parameters: bool = False, compact: bool | None = None
) -> dict[str, Any]:
    """Enumerate write-capable MCP tools with optional schemas."""

    catalog = list_all_actions(include_parameters=include_parameters, compact=compact)
    tools = [tool for tool in catalog.get("tools", []) or [] if tool.get("write_action")]
    return {
        "compact": catalog.get("compact"),
        "tools": tools,
    }


async def list_tools(
    only_write: bool = False,
    only_read: bool = False,
    name_prefix: str | None = None,
) -> dict[str, Any]:
    """Lightweight tool catalog."""

    if only_write and only_read:
        raise ValueError("only_write and only_read cannot both be true")

    catalog = list_all_actions(include_parameters=False, compact=True)
    tools: list[dict[str, Any]] = []
    # In the lightweight list_tools view, hide most introspection helpers when
    # callers ask for "read" tools. This keeps the surface area small for
    # clients that just want application tools, while still exposing
    # list_all_actions as the canonical schema registry.
    hidden_when_only_read = {
        "list_tools",
        "list_resources",
        "list_write_actions",
        "list_write_tools",
    }
    for entry in catalog.get("tools", []) or []:
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        if only_read and name in hidden_when_only_read:
            continue
        if name_prefix and not name.startswith(name_prefix):
            continue

        write_action = bool(entry.get("write_action"))
        if only_write and not write_action:
            continue
        if only_read and write_action:
            continue

        tools.append(
            {
                "name": name,
                "write_action": write_action,
                "write_allowed": bool(entry.get("write_allowed", True)),
                "write_enabled": bool(entry.get("write_enabled", True)),
                "write_auto_approved": bool(entry.get("write_auto_approved", True)),
                "approval_required": bool(entry.get("approval_required", False)),
                "visibility": entry.get("visibility"),
            }
        )

    tools.sort(key=lambda t: t["name"])

    payload: dict[str, Any] = {"tools": tools}
    errors = catalog.get("errors")
    if isinstance(errors, list) and errors:
        payload["errors"] = errors
    return payload


def _normalize_base_path(base_path: str | None) -> str:
    if not base_path:
        return ""
    cleaned = base_path.strip()
    if cleaned in {"", "/"}:
        return ""
    return "/" + cleaned.strip("/")


def list_resources(
    base_path: str | None = None,
    include_parameters: bool = False,
    compact: bool | None = None,
    cursor: int | None = 0,
    limit: int | None = 200,
) -> dict[str, Any]:
    """Return a resource catalog derived from registered tools.

    This is intentionally lightweight and supports pagination.

    Args:
        base_path: Optional prefix prepended to each resource URI.
        include_parameters: When True, include the tool input schema for each
            returned resource. This can be expensive for very large catalogs;
            consider paginating via cursor/limit.
        compact: When True, shorten descriptions.
        cursor: Integer offset into the sorted resource list.
        limit: Maximum number of resources to return (bounded).
    """

    m = _main()
    compact_mode = m.COMPACT_METADATA_DEFAULT if compact is None else compact
    prefix = _normalize_base_path(base_path)

    # Validate + clamp pagination inputs.
    try:
        cursor_i = int(cursor or 0)
    except (TypeError, ValueError):
        cursor_i = 0
    if cursor_i < 0:
        cursor_i = 0

    try:
        limit_i = int(limit or 200)
    except (TypeError, ValueError):
        limit_i = 200

    # Safety cap: avoid giant payloads that can overwhelm clients.
    max_limit = 500
    if limit_i <= 0:
        limit_i = 200
    if limit_i > max_limit:
        limit_i = max_limit

    registry_entries, registry_errors = _iter_tool_registry()

    # Keep introspection endpoints visible even when the registry is damaged.
    from types import SimpleNamespace

    forced_entries = [
        (SimpleNamespace(name="list_all_actions", write_action=False), list_all_actions),
        (SimpleNamespace(name="list_tools", write_action=False), list_tools),
        (SimpleNamespace(name="list_resources", write_action=False), list_resources),
        (SimpleNamespace(name="list_write_actions", write_action=False), list_write_actions),
        (SimpleNamespace(name="list_write_tools", write_action=False), list_write_tools),
    ]

    seen_names: set[str] = set()
    items: list[dict[str, Any]] = []
    for tool, func in forced_entries + list(registry_entries):
        name = _registered_tool_name(tool, func)
        if not name:
            continue
        name_str = str(name)
        if name_str in seen_names:
            continue
        seen_names.add(name_str)

        description = getattr(tool, "description", None) or (func.__doc__ or "")
        description = _clean_description(str(description).strip())

        if compact_mode and description:
            description = description.splitlines()[0].strip() or description

        items.append({"name": name_str, "description": description, "tool": tool, "func": func})

    items.sort(key=lambda entry: entry["name"])
    total = len(items)
    page = items[cursor_i : cursor_i + limit_i]

    resources: list[dict[str, Any]] = []
    for entry in page:
        name = entry["name"]
        resource: dict[str, Any] = {
            "uri": f"{prefix}/tools/{name}",
            "name": name,
            "mimeType": "application/json",
        }
        if entry.get("description"):
            resource["description"] = entry.get("description")
        if include_parameters:
            safe_schema = _schema_for_callable(entry["func"], entry["tool"], tool_name=name)
            resource["input_schema"] = safe_schema
            resource["inputSchema"] = safe_schema
        resources.append(resource)

    end = cursor_i + len(page)
    finite = end >= total
    next_cursor: int | None = None if finite else end

    payload: dict[str, Any] = {
        "resources": resources,
        "finite": finite,
        "cursor": cursor_i,
        "limit": limit_i,
        "total": total,
        "compact": compact_mode,
    }
    if next_cursor is not None:
        # Support both snake_case and camelCase for downstream clients.
        payload["next_cursor"] = next_cursor
        payload["nextCursor"] = next_cursor

    if isinstance(registry_errors, list) and registry_errors:
        payload["errors"] = registry_errors
    return payload


async def describe_tool(
    name: str | None = None,
    names: list[str] | None = None,
    include_parameters: bool = True,
) -> dict[str, Any]:
    """Inspect one or more registered MCP tools by name."""

    if names is None or len(names) == 0:
        if not name:
            raise ValueError("describe_tool requires 'name' or 'names'.")
        names = [name]
    else:
        seen = set()
        normalized: list[str] = []
        for candidate in names:
            if not isinstance(candidate, str):
                raise TypeError("names must be a list of strings.")
            if candidate not in seen:
                seen.add(candidate)
                normalized.append(candidate)
        if name and name not in seen:
            normalized.insert(0, name)
        names = normalized

    if len(names) == 0:
        raise ValueError("describe_tool requires at least one tool name.")
    if len(names) > 10:
        raise ValueError("describe_tool can return at most 10 tools per call.")

    catalog = list_all_actions(include_parameters=include_parameters, compact=False)
    tools_index = {entry.get("name"): entry for entry in catalog.get("tools", [])}

    found: list[dict[str, Any]] = []
    missing: list[str] = []

    for tool_name2 in names:
        entry = tools_index.get(tool_name2)
        if entry is None:
            missing.append(tool_name2)
        else:
            found.append(entry)

    if not found:
        raise ValueError(f"Unknown tool name(s): {', '.join(sorted(set(missing)))}")

    result: dict[str, Any] = {"tools": found}
    first = found[0]
    for key, value in first.items():
        result.setdefault(key, value)

    if missing:
        result["missing_tools"] = sorted(set(missing))

    return result


def _validate_single_tool_args(tool_name: str, args: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate a single candidate payload against a tool's input schema."""

    if args is not None and not isinstance(args, Mapping):
        raise TypeError("args must be a mapping")

    _main()
    tool = None
    func = None
    for candidate_tool, candidate_func in _tool_registry():
        if _registered_tool_name(candidate_tool, candidate_func) == tool_name:
            tool, func = candidate_tool, candidate_func
            break
    if tool is None or func is None:
        available = sorted(
            {name for tool, func in _tool_registry() if (name := _registered_tool_name(tool, func))}
        )
        raise ValueError(f"Unknown tool {tool_name!r}. Available tools: {', '.join(available)}")

    # Keep this consistent with list_all_actions: prefer a dynamically-derived schema.
    schema = _schema_for_callable(func, tool, tool_name=tool_name)

    # Schema validation has been intentionally removed. This helper now performs
    # only minimal shape checks (payload must be an object) and returns the
    # tool's published schema (when available) so clients can self-validate.
    errors: list[dict[str, Any]] = []

    if args is not None and not isinstance(args, Mapping):
        errors.append(
            {
                "message": "payload must be an object",
                "path": [],
                "validator": "type",
                "validator_value": "object",
            }
        )

    base_write_action = bool(_tool_attr(tool, func, "write_action", False))
    gate = _write_gate_state()
    write_auto_approved = gate["write_auto_approved"]
    return {
        "tool": tool_name,
        "valid": len(errors) == 0,
        "errors": errors,
        "schema": schema,
        "visibility": (
            getattr(func, "__mcp_visibility__", None)
            or getattr(tool, "__mcp_visibility__", None)
            or "public"
        ),
        "write_action": base_write_action,
        "write_allowed": gate["write_allowed"],
        "write_enabled": gate["write_enabled"],
        "write_auto_approved": write_auto_approved,
        "write_actions_enabled": gate["write_actions_enabled"],
        "approval_required": _approval_required(base_write_action, write_auto_approved),
    }


async def validate_tool_args(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Deprecated. Schema validation has been removed."""
    raise NotImplementedError("validate_tool_args has been removed")
