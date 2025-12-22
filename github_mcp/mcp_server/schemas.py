from __future__ import annotations

import hashlib
import inspect
import json
import re
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

_SENSITIVE_PATTERNS = [
    (
        re.compile(r"https://x-access-token:([^@/\s]+)@github\.com/"),
        "https://x-access-token:***@github.com/",
    ),
    (re.compile(r"x-access-token:([^@\s]+)@github\.com"), "x-access-token:***@github.com"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "ghp_***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), "github_pat_***"),
]


def _redact_sensitive_text(text: str) -> str:
    """Redact token-like substrings from metadata destined for LLMs."""

    if not isinstance(text, str):
        return text

    redacted = text
    for pat, repl in _SENSITIVE_PATTERNS:
        redacted = pat.sub(repl, redacted)
    return redacted


def _sanitize_metadata_value(value: Any) -> Any:
    """Best-effort deep redaction for schemas and tool metadata."""

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        return _redact_sensitive_text(value)

    if isinstance(value, set):
        # Sets are not JSON-serializable; convert to a stable list so metadata
        # never blocks serialization.
        return [_sanitize_metadata_value(v) for v in value]

    if isinstance(value, Mapping):
        return {k: _sanitize_metadata_value(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_sanitize_metadata_value(v) for v in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_metadata_value(v) for v in value)

    # Fallback: make sure unrecognized types (e.g., datetime objects) never
    # break metadata rendering. Preserve a readable string representation so
    # ChatGPT can still understand the payload.
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)

    return value


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
    description = "\n".join([p for p in parts if p])
    return _redact_sensitive_text(description)

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
            schema = {
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
        elif name == "list_recent_failures":
            schema = {
                "type": "object",
                "properties": {
                    "full_name": {"type": "string"},
                    "branch": {"type": ["string", "null"]},
                    "limit": {"type": "integer"},
                },
                "required": ["full_name"],
                "additionalProperties": True,
            }

        if schema is not None:
            schema = _tighten_schema_properties(schema)
            return _sanitize_metadata_value(schema)

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

        return _sanitize_metadata_value(schema)

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

            return _sanitize_metadata_value(
                {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                    "additionalProperties": True,
                }
            )
    except Exception:  # extremely defensive
        return None

    return None

# ---------------------------------------------------------------------------
# Schema tightening
# ---------------------------------------------------------------------------

_COMMON_ARRAY_STRING_KEYS = {
    "paths", "labels", "assignees", "metricTypes", "resource", "level", "type", "text",
}

_COMMON_OBJECT_NULL_KEYS = {
    "inputs", "variables", "security_and_analysis", "create_payload_overrides", "update_payload_overrides",
}

_COMMON_BOOL_KEYS = {
    "approved", "draft", "push", "reset", "refresh", "recursive", "include_blobs", "include_trees",
    "include_hidden", "include_dirs", "auto_init", "is_template", "has_issues", "has_projects", "has_wiki",
    "has_discussions", "include_all_branches", "clone_to_workspace", "use_temp_venv",
    "installing_dependencies", "mutating", "run_tokenlike_scan", "create_parents", "add_all",
    "discard_uncommitted_changes", "delete_mangled_branch", "reset_base", "enumerate_repo", "dry_run",
    "return_diff",
}

_COMMON_INT_KEYS = {
    "number", "issue_number", "pull_number", "run_id", "job_id", "installation_id", "comment_id",
    "page", "per_page", "limit", "start_line", "max_lines", "timeout_seconds", "poll_interval_seconds",
    "max_jobs", "max_files", "max_depth", "max_results", "max_file_bytes", "resolution", "team_id",
}

_COMMON_STRING_KEYS = {
    "full_name", "owner", "repo", "path", "file_path", "from_path", "to_path", "workspace_path", "target_path",
    "ref", "branch", "base", "head", "base_branch", "new_branch", "base_ref", "from_ref",
    "name", "title", "body", "message", "url", "workflow", "query", "command", "workdir", "handle",
    "min_level", "search_type", "sort", "filter", "state", "status", "event", "visibility",
    "homepage", "description", "affiliation", "owner_type", "template_full_name", "gitignore_template",
    "license_template",
}


def _infer_schema_for_key(key: str) -> Dict[str, Any]:
    """Infer a stricter JSON Schema fragment for common tool argument names.

    `{}` means "anything" in JSON Schema. For AI callers, that reintroduces
    guesswork and prevents preflight validation.

    These inferences are conservative and only applied when a property schema is
    missing or untyped.
    """

    k = (key or "").strip()
    if not k:
        return {}

    if k in _COMMON_ARRAY_STRING_KEYS:
        return {"type": "array", "items": {"type": "string"}}

    if k in _COMMON_OBJECT_NULL_KEYS:
        return {"type": ["object", "null"]}

    if k in _COMMON_BOOL_KEYS:
        return {"type": "boolean"}

    if k in _COMMON_INT_KEYS or k.endswith("_id") or k.endswith("_number"):
        return {"type": "integer"}

    if k in _COMMON_STRING_KEYS:
        return {"type": "string"}

    # Heuristic: many *_at fields are ISO timestamps.
    if k.endswith("_at"):
        return {"type": ["string", "null"]}

    return {}


def _apply_nullability_from_default(prop: Dict[str, Any]) -> None:
    """If a property default is None, allow null in the property type."""

    if "default" not in prop:
        return
    if prop.get("default", object()) is not None:
        return

    t = prop.get("type")
    if isinstance(t, str):
        if t != "null":
            prop["type"] = sorted({t, "null"})
    elif isinstance(t, list):
        if "null" not in t:
            prop["type"] = sorted(set(t + ["null"]))


def _tighten_schema_properties(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Fill in missing/untyped property schemas for common args."""

    props = schema.setdefault("properties", {})
    required = schema.setdefault("required", []) or []

    # Ensure required keys exist in properties.
    for req in list(required):
        if req not in props:
            inferred = _infer_schema_for_key(req)
            if inferred:
                props[req] = inferred

    for key, prop in list(props.items()):
        if not isinstance(prop, dict):
            continue

        needs_type = (not prop) or (prop.get("type") is None)
        if needs_type:
            inferred = _infer_schema_for_key(str(key))
            if inferred:
                merged = dict(inferred)
                if "default" in prop:
                    merged["default"] = prop.get("default")
                    _apply_nullability_from_default(merged)
                props[key] = merged
            continue

        # If it's an array (or includes array), ensure items are present.
        t = prop.get("type")
        is_array = (t == "array") or (isinstance(t, list) and "array" in t)
        if is_array and "items" not in prop:
            inferred = _infer_schema_for_key(str(key))
            if inferred.get("type") == "array" and "items" in inferred:
                prop["items"] = inferred["items"]

        _apply_nullability_from_default(prop)

    return schema


def _format_tool_args_preview(all_args: Mapping[str, Any], *, limit: int = 1200) -> str:
    """Return a single-line, truncated snapshot of tool arguments.

    Render logs are easiest to read when tool args are compact and avoid embedding
    huge blobs (file contents, patches, long commands). For those values we log a
    short summary (length + checksum) and rely on dedicated diff logging for write
    tools.
    """

    if not all_args:
        return "<no args>"

    large_keys = {
        "updated_content",
        "content",
        "body",
        "patch",
        "diff",
        "command",
        "stdout",
        "stderr",
        "controller_log",
    }

    def _sha1_8(s: str) -> str:
        return hashlib.sha1(s.encode("utf-8", errors="replace")).hexdigest()[:8]

    def _summarize(value: Any, *, key: str | None = None, depth: int = 0) -> Any:
        # Keep this strictly single-line friendly.
        if value is None or isinstance(value, (bool, int, float)):
            return value

        if isinstance(value, (bytes, bytearray)):
            return f"<bytes len={len(value)}>"

        if isinstance(value, str):
            # Always summarize large/sensitive keys or anything with whitespace control chars.
            if key in large_keys or len(value) > 180 or any(c in value for c in ("\n", "\r", "\t")):
                return f"<str len={len(value)} sha1={_sha1_8(value)}>"
            return value

        if isinstance(value, Mapping):
            if depth >= 2:
                return f"<dict keys={len(value)}>"
            return {k: _summarize(v, key=str(k), depth=depth + 1) for k, v in value.items()}

        if isinstance(value, (list, tuple)):
            if depth >= 2:
                return f"<list len={len(value)}>"
            return [_summarize(v, depth=depth + 1) for v in value]

        return str(value)

    try:
        safe_args = {k: _summarize(v, key=str(k), depth=0) for k, v in all_args.items()}
        safe_args = _sanitize_metadata_value(safe_args)
        preview = json.dumps(safe_args, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        preview = "<args preview unavailable>"

    # Ensure it is a single line even if something slipped through.
    preview = preview.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    preview = _redact_sensitive_text(preview)

    if len(preview) > limit:
        preview = f"{preview[:limit]}… (+{len(preview) - limit} chars)"

    return preview
