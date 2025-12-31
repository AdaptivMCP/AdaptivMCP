from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

import jsonschema

from github_mcp.config import TOOL_DENYLIST
from github_mcp.mcp_server.context import get_write_allowed
from ._main import _main

_UI_PROMPT_WHEN_WRITE_ALLOWED_TOOLS: set[str] = {
    "apply_text_update_and_commit",
    "commit_workspace",
    "commit_workspace_files",
    "create_branch",
    "create_file",
    "ensure_branch",
    "merge_pull_request",
    "move_file",
    "pr_smoke_test",
    "update_files_and_open_pr",
    "workspace_create_branch",
    "workspace_delete_branch",
    "workspace_self_heal_branch",
}


def _ui_prompt_write_action(tool_name: str, write_action: bool, *, write_allowed: bool) -> bool:
    # UI policy only (does not define whether the tool is a write tool).
    if not write_action:
        return False
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
            "name": "authorize_write_actions",
            "category": "control",
            "description": "Update the server's write-allowed state.",
            "notes": "This toggles the WRITE_ALLOWED flag used by write gating.",
        },
        {
            "name": "create_branch",
            "category": "branch",
            "description": "Create a new branch from a base ref.",
            "notes": "Prefer ensure_branch unless you know the branch does not exist.",
        },
        {
            "name": "ensure_branch",
            "category": "branch",
            "description": "Ensure a branch exists, creating it from a base ref if needed.",
            "notes": "Safe default for preparing branches before commits or PRs.",
        },
        {
            "name": "update_file_and_open_pr",
            "category": "pr",
            "description": "Fast path: commit one file and open a PR without cloning.",
            "notes": "Use for tiny fixes like lint nits or typo corrections.",
        },
        {
            "name": "create_pull_request",
            "category": "pr",
            "description": "Open a GitHub pull request between two branches.",
            "notes": "Usually called indirectly by higher-level tools.",
        },
        {
            "name": "update_files_and_open_pr",
            "category": "pr",
            "description": "Commit multiple files and open a PR in one call.",
            "notes": "Use primarily for docs and multi-file updates.",
        },
        {
            "name": "ensure_workspace_clone",
            "category": "workspace",
            "description": "Ensure a persistent workspace exists for a repo/ref.",
            "notes": "Clones if missing and can optionally reset to the remote ref.",
        },
        {
            "name": "run_command",
            "category": "workspace",
            "description": "Run an arbitrary shell command in a persistent workspace clone.",
            "notes": "Shares the same persistent workspace used by commit tools so edits survive across calls.",
        },
        {
            "name": "commit_workspace",
            "category": "workspace",
            "description": "Commit and optionally push changes from the persistent workspace.",
            "notes": "Stages changes, commits with a provided message, and can push to the effective branch.",
        },
        {
            "name": "commit_workspace_files",
            "category": "workspace",
            "description": "Commit a specific list of files from the persistent workspace.",
            "notes": "Use to avoid staging temporary artifacts while still pushing changes to the branch.",
        },
        {
            "name": "run_tests",
            "category": "workspace",
            "description": "Run tests (default: pytest) inside the persistent workspace clone.",
            "notes": "Preferred way to run tests; shares the persistent workspace with run_command and commit helpers.",
        },
        {
            "name": "trigger_workflow_dispatch",
            "category": "workflow",
            "description": "Trigger a GitHub Actions workflow via workflow_dispatch.",
            "notes": "Use only when Joey explicitly asks to run a workflow.",
        },
        {
            "name": "trigger_and_wait_for_workflow",
            "category": "workflow",
            "description": "Trigger a workflow and poll until completion or timeout.",
            "notes": "Summarize the run result in your response.",
        },
        {
            "name": "create_issue",
            "category": "issue",
            "description": "Open a GitHub issue with optional body, labels, and assignees.",
            "notes": "Use to capture new work items or questions.",
        },
        {
            "name": "update_issue",
            "category": "issue",
            "description": "Update fields on an existing GitHub issue.",
            "notes": "Adjust scope, status, or ownership directly in the issue.",
        },
        {
            "name": "comment_on_issue",
            "category": "issue",
            "description": "Post a comment on an existing GitHub issue.",
            "notes": "Log progress updates and decisions.",
        },
        {
            "name": "merge_pull_request",
            "category": "pr",
            "description": "Merge an existing PR using the chosen method.",
            "notes": "Assistants should only merge when Joey explicitly requests it.",
        },
        {
            "name": "close_pull_request",
            "category": "pr",
            "description": "Close an existing PR without merging.",
            "notes": "Only when Joey asks to close a PR.",
        },
        {
            "name": "comment_on_pull_request",
            "category": "pr",
            "description": "Post a comment on an existing PR.",
            "notes": "Use for status, summaries, or test results if Joey likes that pattern.",
        },
    ]

    filtered = [tool for tool in tools if tool.get("name") not in TOOL_DENYLIST]
    return {"tools": filtered}


def _tool_attr(tool: Any, func: Any, name: str, default: Any = None) -> Any:
    """Best-effort attribute resolution across tool and function wrappers."""
    if hasattr(tool, name):
        return getattr(tool, name)
    private = f"__mcp_{name}__"
    if hasattr(func, private):
        return getattr(func, private)
    return default


def _tool_tags(tool: Any, func: Any) -> list[str]:
    tags = getattr(tool, "tags", None)
    if tags is None or tags == [] or tags == set():
        tags = getattr(func, "__mcp_tags__", None)
    if not tags:
        return []
    return [str(tag) for tag in tags if str(tag).strip()]


def list_all_actions(include_parameters: bool = False, compact: Optional[bool] = None) -> Dict[str, Any]:
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
        write_enabled = (not base_write_action) or write_allowed

        tool_info: Dict[str, Any] = {
            "name": name_str,
            "visibility": str(visibility),
            # Correct semantic classification:
            "write_action": base_write_action,
            # Dynamic gating:
            "write_enabled": bool(write_enabled),
            # UI policy hint (separate from write_action):
            "ui_prompt": _ui_prompt_write_action(
                name_str,
                base_write_action,
                write_allowed=write_allowed,
            ),
        }

        operation = _tool_attr(tool, func, "operation", None)
        risk_level = _tool_attr(tool, func, "risk_level", None)
        if operation is not None:
            tool_info["operation"] = operation
        if risk_level is not None:
            tool_info["risk_level"] = risk_level

        if description:
            tool_info["description"] = description

        if not compact_mode:
            tool_info["tags"] = sorted(_tool_tags(tool, func))

        if include_parameters:
            schema = getattr(func, "__mcp_input_schema__", None)
            if not isinstance(schema, Mapping):
                schema = m._normalize_input_schema(tool)
            if schema is None:
                schema = {"type": "object", "properties": {}}
            tool_info["input_schema"] = schema

        tools.append(tool_info)

    if "list_all_actions" not in seen_names:
        synthetic: Dict[str, Any] = {
            "name": "list_all_actions",
            "description": "Enumerate every available MCP tool with optional schemas.",
            "visibility": "public",
            "write_action": False,
            "write_enabled": True,
            "ui_prompt": False,
        }
        if not compact_mode:
            synthetic["tags"] = ["meta"]
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
        "write_actions_enabled": bool(get_write_allowed(refresh_after_seconds=0.0)),
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

        tools.append(
            {
                "name": name,
                "write_action": write_action,
                "write_enabled": bool(entry.get("write_enabled", True)),
                "operation": entry.get("operation"),
                "risk_level": entry.get("risk_level"),
                "visibility": entry.get("visibility"),
            }
        )

    tools.sort(key=lambda t: t["name"])
    m = _main()
    return {
        "write_actions_enabled": bool(get_write_allowed(refresh_after_seconds=0.0)),
        "tools": tools,
    }


async def describe_tool(
    name: Optional[str] = None,
    names: Optional[List[str]] = None,
    include_parameters: bool = True,
    tool_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Inspect one or more registered MCP tools by name."""
    # Back-compat: some callers pass tool_name.
    if not name and tool_name:
        name = tool_name

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
    if schema is None:
        raise ValueError(f"Tool {tool_name!r} does not expose an input schema")

    normalized_args = dict(args or {})

    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    errors = [
        {
            "message": error.message,
            "path": list(error.absolute_path),
            "validator": error.validator,
            "validator_value": error.validator_value,
        }
        for error in sorted(validator.iter_errors(normalized_args), key=str)
    ]

    base_write_action = bool(_tool_attr(tool, func, "write_action", False))
    write_allowed = bool(get_write_allowed(refresh_after_seconds=0.0))

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
        "write_enabled": (not base_write_action) or write_allowed,
    }


async def validate_tool_args(
    tool_name: Optional[str] = None,
    payload: Optional[Mapping[str, Any]] = None,
    tool_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Validate candidate payload(s) against tool input schemas without running them."""
    if not tool_names:
        if not tool_name:
            raise ValueError("validate_tool_args requires 'tool_name' or 'tool_names'.")
        return _validate_single_tool_args(tool_name, payload)

    seen = set()
    normalized: List[str] = []
    for candidate in tool_names:
        if not isinstance(candidate, str):
            raise TypeError("tool_names must be a list of strings.")
        if candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)

    if tool_name and tool_name not in seen:
        normalized.insert(0, tool_name)

    if len(normalized) == 0:
        raise ValueError("validate_tool_args requires at least one tool name.")
    if len(normalized) > 10:
        raise ValueError("validate_tool_args can validate at most 10 tools per call.")

    results: List[Dict[str, Any]] = []
    missing: List[str] = []

    for name in normalized:
        try:
            result = _validate_single_tool_args(name, payload)
        except ValueError as exc:
            msg = str(exc)
            if msg.startswith("Unknown tool ") and "Available tools:" in msg:
                missing.append(name)
                continue
            raise
        else:
            results.append(result)

    if not results:
        raise ValueError(f"Unknown tool name(s): {', '.join(sorted(set(missing)))}")

    response: Dict[str, Any] = {"results": results}
    first = results[0]
    for key, value in first.items():
        response.setdefault(key, value)

    if missing:
        response["missing_tools"] = sorted(set(missing))

    return response
