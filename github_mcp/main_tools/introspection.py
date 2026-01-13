from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from github_mcp.mcp_server.context import get_write_allowed
from github_mcp.mcp_server.schemas import _jsonable
from ._main import _main

_UI_PROMPT_WHEN_WRITE_ALLOWED_TOOLS: set[str] = set()


def _ui_prompt_write_action(tool_name: str, write_action: bool, *, write_allowed: bool) -> bool:
    # UI policy only (does not define whether the tool is a write tool).
    if not write_action:
        return False
    # When write_allowed is false, require confirmation for any write action.
    if not write_allowed:
        return True
    if tool_name in _UI_PROMPT_WHEN_WRITE_ALLOWED_TOOLS:
        return True
    lowered = tool_name.lower()
    return "commit" in lowered or "push" in lowered


def list_write_tools() -> Dict[str, Any]:
    """Describe write-capable tools exposed by this server.

    This is intended for assistants to discover what they can do safely without
    reading the entire main.py.
    """

    tools = [
        {
            "name": "create_branch",
            "category": "branch",
            "description": "Create a new branch from a base ref.",
        },
        {
            "name": "ensure_branch",
            "category": "branch",
            "description": "Ensure a branch exists, creating it from a base ref if needed.",
        },
        {
            "name": "update_file_and_open_pr",
            "category": "pr",
            "description": "Fast path: commit one file and open a PR without cloning.",
        },
        {
            "name": "create_pull_request",
            "category": "pr",
            "description": "Open a GitHub pull request between two branches.",
        },
        {
            "name": "update_files_and_open_pr",
            "category": "pr",
            "description": "Commit multiple files and open a PR in one call.",
        },
        {
            "name": "ensure_workspace_clone",
            "category": "workspace",
            "description": "Ensure a persistent workspace exists for a repo/ref.",
        },
        {
            "name": "commit_workspace",
            "category": "workspace",
            "description": "Commit and optionally push changes from the persistent workspace.",
        },
        {
            "name": "apply_patch",
            "category": "workspace",
            "description": "Apply a unified diff patch inside the persistent workspace clone.",
        },
        {
            "name": "commit_workspace_files",
            "category": "workspace",
            "description": "Commit a specific list of files from the persistent workspace.",
        },
        {
            "name": "run_tests",
            "category": "workspace",
            "description": "Run tests (default: pytest) inside the persistent workspace clone.",
        },
        {
            "name": "trigger_workflow_dispatch",
            "category": "workflow",
            "description": "Trigger a GitHub Actions workflow via workflow_dispatch.",
        },
        {
            "name": "trigger_and_wait_for_workflow",
            "category": "workflow",
            "description": "Trigger a workflow and poll until completion or timeout.",
        },
        {
            "name": "create_issue",
            "category": "issue",
            "description": "Open a GitHub issue with optional body, labels, and assignees.",
        },
        {
            "name": "update_issue",
            "category": "issue",
            "description": "Update fields on an existing GitHub issue.",
        },
        {
            "name": "comment_on_issue",
            "category": "issue",
            "description": "Post a comment on an existing GitHub issue.",
        },
        {
            "name": "merge_pull_request",
            "category": "pr",
            "description": "Merge an existing PR using the chosen method.",
        },
        {
            "name": "close_pull_request",
            "category": "pr",
            "description": "Close an existing PR without merging.",
        },
        {
            "name": "comment_on_pull_request",
            "category": "pr",
            "description": "Post a comment on an existing PR.",
        },
    ]

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
    """Return tags for a tool.

    Tags are intentionally suppressed. Some clients interpret tags as
    policy/execution hints and may misclassify tools when tags are present.
    """

    return []


def list_all_actions(
    include_parameters: bool = False, compact: Optional[bool] = None
) -> Dict[str, Any]:
    """Enumerate every available MCP tool with optional schemas.

    Canonical “schema registry” used by assistants/clients.
    - Inherent tool classification is always reported as write_action (True/False).
    - Dynamic gating is reported separately as write_enabled per tool.
    """

    m = _main()
    compact_mode = m.COMPACT_METADATA_DEFAULT if compact is None else compact

    tools: List[Dict[str, Any]] = []
    seen_names: set[str] = set()
    write_allowed = bool(get_write_allowed(refresh_after_seconds=0.0))

    for tool, func in m._REGISTERED_MCP_TOOLS:
        name = getattr(tool, "name", None) or getattr(func, "__name__", None)
        if not name:
            continue
        name_str = str(name)
        if name_str in seen_names:
            continue
        seen_names.add(name_str)

        description = getattr(tool, "description", None) or (func.__doc__ or "")
        description = description.strip()

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
        # Approval-gated writes:
        # - All tools remain enabled.
        # - write_actions_enabled indicates whether writes are auto-approved.
        # - write_allowed indicates whether the tool is executable.
        write_enabled = True
        tool_write_allowed = bool(write_enabled)
        approval_required = bool(base_write_action and not write_allowed)

        tool_info: Dict[str, Any] = {
            "name": name_str,
            "visibility": str(visibility),
            # Correct semantic classification:
            "write_action": base_write_action,
            # Executability (approval-gated writes still execute).
            "write_allowed": bool(tool_write_allowed),
            "write_auto_approved": bool(write_allowed),
            "approval_required": bool(approval_required),
            # Dynamic gating:
            "write_enabled": bool(write_enabled),
            # UI policy hint (separate from write_action):
            "ui_prompt": _ui_prompt_write_action(
                name_str,
                base_write_action,
                write_allowed=write_allowed,
            ),
        }

        if description:
            tool_info["description"] = description

        # Do not surface tags or risk metadata. Tool classification is expressed
        # exclusively via write_action plus the approval gating fields.

        if include_parameters:
            schema = getattr(func, "__mcp_input_schema__", None)
            if not isinstance(schema, Mapping):
                schema = m._normalize_input_schema(tool)
            if schema is None:
                schema = {"type": "object", "properties": {}}
            safe_schema = _jsonable(schema)
            if not isinstance(safe_schema, Mapping):
                safe_schema = {"type": "object", "properties": {}}
            tool_info["input_schema"] = safe_schema

        tools.append(tool_info)

    if "list_all_actions" not in seen_names:
        synthetic: Dict[str, Any] = {
            "name": "list_all_actions",
            "description": "Enumerate every available MCP tool with optional schemas.",
            "visibility": "public",
            "write_action": False,
            "write_allowed": True,
            "write_enabled": True,
            "ui_prompt": False,
        }
        if include_parameters:
            synthetic["input_schema"] = {
                "type": "object",
                "properties": {
                    "include_parameters": {"type": "boolean"},
                    "compact": {"type": ["boolean", "null"]},
                },
                "additionalProperties": False,
            }
        tools.append(synthetic)

    tools.sort(key=lambda entry: entry["name"])

    return {
        "compact": compact_mode,
        # write_actions_enabled represents whether writes are auto-approved.
        # When false, clients should prompt before executing write tools.
        "write_actions_enabled": bool(get_write_allowed(refresh_after_seconds=0.0)),
        "tools": tools,
    }


def list_write_actions(
    include_parameters: bool = False, compact: Optional[bool] = None
) -> Dict[str, Any]:
    """Enumerate write-capable MCP tools with optional schemas."""

    catalog = list_all_actions(include_parameters=include_parameters, compact=compact)
    tools = [tool for tool in catalog.get("tools", []) or [] if tool.get("write_action")]
    return {
        "compact": catalog.get("compact"),
        "write_actions_enabled": catalog.get("write_actions_enabled"),
        "tools": tools,
    }


async def list_tools(
    only_write: bool = False,
    only_read: bool = False,
    name_prefix: Optional[str] = None,
) -> Dict[str, Any]:
    """Lightweight tool catalog."""

    if only_write and only_read:
        raise ValueError("only_write and only_read cannot both be true")

    catalog = list_all_actions(include_parameters=False, compact=True)
    write_auto_approved = bool(get_write_allowed(refresh_after_seconds=0.0))
    tools: List[Dict[str, Any]] = []
    for entry in catalog.get("tools", []) or []:
        name = entry.get("name")
        if not isinstance(name, str):
            continue
        if name_prefix and not name.startswith(name_prefix):
            continue

        write_action = bool(entry.get("write_action"))
        if only_write and not write_action:
            continue
        if only_read and write_action:
            continue

        tool_write_auto_approved = bool(entry.get("write_auto_approved", write_auto_approved))
        tool_approval_required = bool(
            entry.get("approval_required", bool(write_action and not tool_write_auto_approved))
        )

        tools.append(
            {
                "name": name,
                "write_action": write_action,
                "write_allowed": bool(entry.get("write_allowed", True)),
                "write_auto_approved": bool(tool_write_auto_approved),
                "approval_required": bool(tool_approval_required),
                "write_enabled": bool(entry.get("write_enabled", True)),
                "visibility": entry.get("visibility"),
            }
        )

    tools.sort(key=lambda t: t["name"])

    return {
        "write_actions_enabled": bool(write_auto_approved),
        "tools": tools,
    }


async def describe_tool(
    name: Optional[str] = None,
    names: Optional[List[str]] = None,
    include_parameters: bool = True,
) -> Dict[str, Any]:
    """Inspect one or more registered MCP tools by name."""

    if names is None or len(names) == 0:
        if not name:
            raise ValueError("describe_tool requires 'name' or 'names'.")
        names = [name]
    else:
        seen = set()
        normalized: List[str] = []
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

    found: List[Dict[str, Any]] = []
    missing: List[str] = []

    for tool_name2 in names:
        entry = tools_index.get(tool_name2)
        if entry is None:
            missing.append(tool_name2)
        else:
            found.append(entry)

    if not found:
        raise ValueError(f"Unknown tool name(s): {', '.join(sorted(set(missing)))}")

    result: Dict[str, Any] = {"tools": found}
    first = found[0]
    for key, value in first.items():
        result.setdefault(key, value)

    if missing:
        result["missing_tools"] = sorted(set(missing))

    return result


def _validate_single_tool_args(tool_name: str, args: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate a single candidate payload against a tool's input schema."""

    if args is not None and not isinstance(args, Mapping):
        raise TypeError("args must be a mapping")

    m = _main()
    found = m._find_registered_tool(tool_name)
    if found is None:
        available = sorted(
            set(
                getattr(tool, "name", None) or getattr(func, "__name__", None)
                for tool, func in m._REGISTERED_MCP_TOOLS
                if getattr(tool, "name", None) or getattr(func, "__name__", None)
            )
        )
        raise ValueError(f"Unknown tool {tool_name!r}. Available tools: {', '.join(available)}")

    tool, func = found

    schema = getattr(func, "__mcp_input_schema__", None)
    if not isinstance(schema, Mapping):
        schema = m._normalize_input_schema(tool)

    # Schema validation has been intentionally removed. This helper now performs
    # only minimal shape checks (payload must be an object) and returns the
    # tool's published schema (when available) so clients can self-validate.
    errors: List[Dict[str, Any]] = []

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
    write_allowed = bool(get_write_allowed(refresh_after_seconds=0.0))
    approval_required = bool(base_write_action and not write_allowed)

    return {
        "tool": tool_name,
        "valid": len(errors) == 0,
        "errors": errors,
        "schema": _jsonable(schema) if isinstance(schema, Mapping) else None,
        "visibility": (
            getattr(func, "__mcp_visibility__", None)
            or getattr(tool, "__mcp_visibility__", None)
            or "public"
        ),
        "write_action": base_write_action,
        # Tool is executable even when write auto-approval is off.
        "write_allowed": True,
        "write_auto_approved": bool(write_allowed),
        "approval_required": bool(approval_required),
        "write_enabled": True,
    }


async def validate_tool_args(*args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Deprecated. Schema validation has been removed."""
    raise NotImplementedError("validate_tool_args has been removed")
