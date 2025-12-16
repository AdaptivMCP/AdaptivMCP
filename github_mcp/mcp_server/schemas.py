from __future__ import annotations

import inspect
import json
from typing import Any, Dict, Mapping, Optional

from github_mcp.mcp_server.context import CONTROLLER_REPO, _TOOL_EXAMPLES
from github_mcp.mcp_server.registry import _REGISTERED_MCP_TOOLS


_TITLE_TOKEN_MAP = {
    "api": "API",
    "id": "ID",
    "mcp": "MCP",
    "oauth": "OAuth",
    "pr": "PR",
    "prs": "PRs",
    "repo": "Repo",
    "repos": "Repos",
    "sse": "SSE",
    "url": "URL",
    "gh": "GH",
    "github": "GitHub",
}


def _title_from_tool_name(name: str) -> str:
    parts = [p for p in (name or "").strip().split("_") if p]
    if not parts:
        return name
    out: list[str] = []
    for part in parts:
        lower = part.lower()
        mapped = _TITLE_TOKEN_MAP.get(lower)
        if mapped:
            out.append(mapped)
        elif len(part) <= 3 and lower.isalpha():
            out.append(part.upper())
        else:
            out.append(part.capitalize())
    return " ".join(out)

def _stringify_annotation(annotation: Any) -> str:
    """Return a deterministic, LLM-friendly description of a parameter type."""

    if annotation is inspect.Signature.empty:
        return "any type"
    if isinstance(annotation, type):
        return annotation.__name__
    if getattr(annotation, "__name__", None):
        return annotation.__name__
    return str(annotation)


def _normalize_tool_description(
    func, signature: Optional[inspect.Signature], *, llm_level: str
) -> str:
    """Return a concise, UI-friendly description for the MCP tool."""

    raw_doc = func.__doc__ or ""
    raw_lines = [line.strip() for line in raw_doc.strip().splitlines() if line.strip()]
    base = raw_lines[0] if raw_lines else ""
    if base.lower().startswith("delegates to"):
        base = ""

    title = _title_from_tool_name(getattr(func, "__name__", "") or "")
    if not base:
        base = f"{title}."
    elif not base.endswith((".", "!", "?")):
        base = f"{base}."

    required: list[str] = []
    optional: list[str] = []
    if signature is not None:
        for name, param in signature.parameters.items():
            if name in {"self", "cls"}:
                continue
            if param.default is inspect.Signature.empty:
                required.append(name)
            else:
                optional.append(name)

    scope = "write" if llm_level == "advanced" else "read"
    required_summary = f"Required: {', '.join(required)}." if required else ""
    optional_summary = f"Optional: {', '.join(optional)}." if optional else ""

    alias_summary = (
        "Aliases: owner+repo→full_name; branch→ref; file_path→path; "
        "base→base_branch; head→new_branch."
    )
    default_summary = f"Defaults: full_name defaults to {CONTROLLER_REPO}."
    example = _TOOL_EXAMPLES.get(getattr(func, "__name__", ""))
    example_summary = f"Example: {example}" if example else ""

    parts = [
        base,
        f"Scope: {scope}.",
        required_summary,
        optional_summary,
        alias_summary,
        default_summary,
        example_summary,
    ]
    return "\n".join([p for p in parts if p])

def _preflight_tool_args(tool: Any, raw_args: Mapping[str, Any]) -> None:
    """Placeholder for JSON Schema-based preflight validation.

    The controller already enforces argument correctness via dedicated runtime
    checks and tests for each tool. Until the auto-generated MCP schemas are
    fully aligned with those semantics, strict preflight validation is disabled
    so that tools behave according to the tested controller contract instead of
    the provisional schemas.
    """

    # Intentionally a no-op: rely on the tools' own validation and tests.
    return None

def _normalize_input_schema(tool: Any) -> Optional[Dict[str, Any]]:
    if tool is None:
        return None

    name = getattr(tool, "name", None)

    # Preflight validation is intentionally relaxed elsewhere (see _preflight_tool_args).
    # This helper should still surface a best-effort JSON schema for *every* tool so
    # clients can render argument names/types reliably.

    # Prefer the underlying MCP tool's explicit inputSchema when available.
    raw_schema = getattr(tool, "inputSchema", None)
    schema: Optional[Dict[str, Any]] = None
    if raw_schema is not None:
        # FastMCP tools typically expose a Pydantic model here.
        if hasattr(raw_schema, "model_dump"):
            schema = raw_schema.model_dump()
        elif isinstance(raw_schema, dict):
            schema = dict(raw_schema)

    # that do not currently expose an inputSchema via the MCP layer. This
    # keeps describe_tool and validate_tool_args useful without requiring
    # every tool to be fully annotated.
    if schema is None:
        if name == "list_workflow_runs":
            return {
                "type": "object",
                "properties": {
                    "full_name": {"type": "string"},
                    "branch": {"type": ["string", "null"]},
                    "status": {"type": ["string", "null"]},
                    "event": {"type": ["string", "null"]},
                    "per_page": {"type": "integer", "minimum": 1},
                    "page": {"type": "integer", "minimum": 1},
                },
                "required": ["full_name"],
                "additionalProperties": True,
            }

        if name == "list_recent_failures":
            return {
                "type": "object",
                "properties": {
                    "full_name": {"type": "string"},
                    "branch": {"type": ["string", "null"]},
                    "limit": {"type": "integer"},
                },
                "required": ["full_name"],
                "additionalProperties": True,
            }

    # At this point we have either a concrete schema from the MCP layer or
    # None. When a schema is present, we sometimes need to tweak it slightly
    # for backwards compatibility with the controller's expectations.
    if schema is not None:
        props = schema.setdefault("properties", {})

        # run_command: allow ref to be string or null so callers can pass
        # None and rely on controller defaults without tripping JSON Schema.
        if name == "run_command":
            ref_prop = props.get("ref")
            if isinstance(ref_prop, dict):
                existing_type = ref_prop.get("type")
                if isinstance(existing_type, str):
                    if existing_type != "null":
                        ref_prop["type"] = sorted({existing_type, "null"})
                elif isinstance(existing_type, list):
                    if "null" not in existing_type:
                        ref_prop["type"] = sorted(set(existing_type + ["null"]))

        # commit_workspace_files: files should be a list of strings.
        if name == "commit_workspace_files":
            files_prop = props.get("files")
            if isinstance(files_prop, dict):
                files_prop["type"] = "array"
                files_prop["items"] = {"type": "string"}

        # cache_files / fetch_files / get_cached_files: paths should be a list of strings.
        if name in {"cache_files", "fetch_files", "get_cached_files"}:
            paths_prop = props.get("paths")
            if isinstance(paths_prop, dict):
                paths_prop["type"] = "array"
                paths_prop["items"] = {"type": "string"}

        # update_files_and_open_pr: files should be a list of objects.
        if name == "update_files_and_open_pr":
            files_prop = props.get("files")
            if isinstance(files_prop, dict):
                files_prop["type"] = "array"
                files_prop["items"] = {"type": "object"}

        # create_issue / update_issue: labels and assignees should allow lists
        # of strings as well as null. update_issue.state should allow string
        # so the tool can enforce allowed values itself.
        if name in {"create_issue", "update_issue"}:
            for key in ("labels", "assignees"):
                prop = props.get(key)
                if isinstance(prop, dict):
                    existing_type = prop.get("type")
                    types: set[str] = set()
                    if isinstance(existing_type, str):
                        types.add(existing_type)
                    elif isinstance(existing_type, list):
                        types.update(existing_type)
                    if not types:
                        types.add("null")
                    types.add("array")
                    prop["type"] = sorted(types)
                    prop["items"] = {"type": "string"}

            if name == "update_issue":
                state_prop = props.get("state")
                if isinstance(state_prop, dict):
                    existing_type = state_prop.get("type")
                    types: set[str] = set()
                    if isinstance(existing_type, str):
                        types.add(existing_type)
                    elif isinstance(existing_type, list):
                        types.update(existing_type)
                    types.update({"string", "null"})
                    state_prop["type"] = sorted(types)

        # describe_tool: names can be string, array of strings, or null.
        if name == "describe_tool":
            names_prop = props.get("names")
            if isinstance(names_prop, dict):
                existing_type = names_prop.get("type")
                types: set[str] = set()
                if isinstance(existing_type, str):
                    types.add(existing_type)
                elif isinstance(existing_type, list):
                    types.update(existing_type)
                types.update({"string", "array", "null"})
                names_prop["type"] = sorted(types)
                names_prop["items"] = {"type": "string"}

        # validate_tool_args: payload should allow objects; tool_names should
        # allow a list of strings as well as null.
        if name == "validate_tool_args":
            payload_prop = props.get("payload")
            if isinstance(payload_prop, dict):
                existing_type = payload_prop.get("type")
                types: set[str] = set()
                if isinstance(existing_type, str):
                    types.add(existing_type)
                elif isinstance(existing_type, list):
                    types.update(existing_type)
                types.update({"object", "null"})
                payload_prop["type"] = sorted(types)

            tool_names_prop = props.get("tool_names")
            if isinstance(tool_names_prop, dict):
                existing_type = tool_names_prop.get("type")
                types: set[str] = set()
                if isinstance(existing_type, str):
                    types.add(existing_type)
                elif isinstance(existing_type, list):
                    types.update(existing_type)
                types.update({"array", "string", "null"})
                tool_names_prop["type"] = sorted(types)
                tool_names_prop["items"] = {"type": "string"}

        # Final normalization: always surface an object schema shape.
        if isinstance(schema, dict):
            if schema.get("type") is None:
                schema["type"] = "object"
            schema.setdefault("properties", {})
            schema.setdefault("required", [])
            schema.setdefault("additionalProperties", True)

        # list_recent_failures: if the MCP schema provided a minimum on limit,
        # drop it so the tool's own ValueError semantics are preserved.
        if name == "list_recent_failures":
            limit_prop = props.get("limit")
            if isinstance(limit_prop, dict):
                limit_prop.pop("minimum", None)

        return schema

    # As a final fallback, derive a best-effort JSON schema from the
    # registered function's Python signature so that describe_tool and
    # list_all_actions can still surface argument names and a reasonable
    # required/optional split even when the MCP layer does not publish an
    # explicit inputSchema.
    try:
        import inspect as _inspect
    except Exception:  # extremely defensive
        return None

    try:
        # Find the Python function associated with this tool so we can inspect
        # its signature.
        for registered_tool, func in _REGISTERED_MCP_TOOLS:
            if registered_tool is not tool:
                continue

            try:
                target_func = _inspect.unwrap(func)
                sig = _inspect.signature(target_func)
            except (TypeError, ValueError):
                return None

            properties: Dict[str, Any] = {}
            required: list[str] = []

            def _annotation_to_schema(ann: Any) -> Dict[str, Any]:
                """Convert a Python type annotation to a shallow JSON Schema fragment.

                This is best-effort and intentionally permissive; it exists to make
                tool metadata stable for clients and assistants.
                """

                try:
                    from typing import get_args, get_origin
                except Exception:  # pragma: no cover
                    def get_args(_a):
                        return ()

                    def get_origin(_a):
                        return None

                origin = get_origin(ann)
                args = get_args(ann) or ()

                # Optional/Union handling (focus on adding null).
                if origin is None and hasattr(ann, '__origin__'):
                    origin = getattr(ann, '__origin__', None)
                    args = getattr(ann, '__args__', ()) or ()

                if origin is not None and origin is getattr(__import__('typing'), 'Union', None):
                    non_null = [a for a in args if a is not type(None)]  # noqa: E721
                    nullable = len(non_null) != len(args)
                    # If Union[T, None], keep the richer schema for T and add null.
                    if len(non_null) == 1:
                        schema = _annotation_to_schema(non_null[0])
                        if nullable:
                            tv = schema.get('type')
                            if isinstance(tv, str):
                                schema['type'] = sorted({tv, 'null'})
                            elif isinstance(tv, list):
                                schema['type'] = sorted(set(tv + ['null']))
                            else:
                                schema['type'] = ['null']
                        return schema

                    # For wider unions, degrade to a simple type union when possible.
                    types: set[str] = set()
                    for a in non_null:
                        frag = _annotation_to_schema(a)
                        t = frag.get('type')
                        if isinstance(t, str):
                            types.add(t)
                        elif isinstance(t, list):
                            types.update(t)
                    if nullable:
                        types.add('null')
                    return {'type': sorted(types)} if types else ({'type': ['null']} if nullable else {})

                # Containers: list/tuple/set and typing equivalents.
                if origin in (list, tuple, set):
                    item_schema: Dict[str, Any] = {}
                    if args:
                        item_schema = _annotation_to_schema(args[0])
                    out: Dict[str, Any] = {'type': 'array'}
                    if item_schema:
                        out['items'] = item_schema
                    return out

                if origin is dict:
                    return {'type': 'object'}

                # Primitives
                if ann in (str, bytes):
                    return {'type': 'string'}
                if ann is int:
                    return {'type': 'integer'}
                if ann is float:
                    return {'type': 'number'}
                if ann is bool:
                    return {'type': 'boolean'}

                # Plain builtins
                if ann in (list, tuple, set):
                    return {'type': 'array'}
                if ann is dict:
                    return {'type': 'object'}

                return {}


            for param_name, param in sig.parameters.items():
                if param.kind in (
                    _inspect.Parameter.VAR_POSITIONAL,
                    _inspect.Parameter.VAR_KEYWORD,
                ):
                    # *args / **kwargs do not map cleanly to JSON object
                    # properties; skip them for the best-effort schema.
                    continue
                if param_name in ("self", "cls"):
                    continue

                prop: Dict[str, Any] = {}

                if param.annotation is not _inspect._empty:
                    prop.update(_annotation_to_schema(param.annotation))

                if param.default is _inspect._empty:
                    required.append(param_name)
                else:
                    # Defaults are helpful hints but may not always be
                    # JSON-serializable; they are included on a best-effort
                    # basis only.
                    if isinstance(param.default, (str, int, float, bool)) or param.default is None:
                        prop["default"] = param.default

                    if param.default is None:
                        tv = prop.get("type")
                        if isinstance(tv, str):
                            if tv != "null":
                                prop["type"] = sorted({tv, "null"})
                        elif isinstance(tv, list):
                            if "null" not in tv:
                                prop["type"] = sorted(set(tv + ["null"]))

                properties[param_name] = prop

            return {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": True,
            }
    except Exception:  # extremely defensive
        return None

    return None

def _format_tool_args_preview(all_args: Mapping[str, Any], *, limit: int = 1200) -> str:
    """Return a human-friendly, truncated snapshot of tool arguments.

    Avoid returning strings that contain literal ``\\n`` sequences (double-escaped
    newlines) because those show up as `\\n` in client UIs and confuse assistants.
    """

    if not all_args:
        return "<no args>"

    try:
        preview = json.dumps(all_args, default=str, ensure_ascii=False)
    except Exception:
        preview = repr(all_args)

    # If json.dumps produced escaped control sequences, make them readable.
    # Intentionally narrow (only \\n, \\r\\n, \\t) to avoid surprising transforms.
    if isinstance(preview, str) and "\\n" in preview and "\n" not in preview:
        preview = preview.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")

    if len(preview) > limit:
        preview = f"{preview[:limit]}… (+{len(preview) - limit} chars)"

    return preview
