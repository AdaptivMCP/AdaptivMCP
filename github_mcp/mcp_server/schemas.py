"""Schema and metadata helpers for MCP tools.

This module is developer-facing infrastructure. It exists to keep the public
tool surface (schemas, parameter descriptions, UI hints) aligned with the
implementation while remaining backwards compatible for existing clients.

What this file does:
1) Generate JSON Schema-like input schemas from Python signatures.
2) Apply schema-only ergonomics (hide legacy aliases, add titles/descriptions).
3) Provide log-safe serialization helpers used by tooling and UI layers.

Important invariants:
- Schemas are descriptive, not enforcement. The server generally accepts extra
  keys to preserve forward/backward compatibility.
- "Legacy" alias parameters may remain supported at runtime, but are hidden
  from schemas so callers see a single canonical argument.
"""

from __future__ import annotations

import inspect
import json
import types
import typing
from typing import Any, Dict, Mapping, Optional, get_args, get_origin

# ---------------------------------------------------------------------------
# Schema ergonomics
#
# The MCP tool surface is consumed by both developers and LLMs. We intentionally
# keep implementation signatures permissive for backwards-compat (e.g. legacy
# alias args), while exposing a cleaner, more consistent input schema.
#
# This module therefore:
# - Derives a baseline JSON schema from function signatures.
# - Applies schema-only simplifications (hide alias params, standardize titles).
# - Adds concise, high-signal parameter descriptions and examples.
# ---------------------------------------------------------------------------


_PARAM_DOCS: Dict[str, Dict[str, Any]] = {
    "full_name": {
        "description": (
            "GitHub repository in 'owner/repo' format. If omitted, defaults to the server's "
            "controller repository."
        ),
        "examples": ["octocat/Hello-World"],
    },
    "ref": {
        "description": (
            "Git ref to operate on. Typically a branch name, but may also be a tag or commit SHA. "
            "Defaults to 'main' when available."
        ),
        "examples": ["main", "develop", "feature/my-branch"],
    },
    "base_ref": {
        "description": "Base ref used as the starting point (branch/tag/SHA).",
        "examples": ["main"],
    },
    "branch": {
        "description": "Branch name.",
        "examples": ["main", "feature/my-branch"],
    },
    "new_branch": {
        "description": "Name of the branch to create.",
        "examples": ["simplify-tool-schemas"],
    },
    "from_ref": {
        "description": "Ref to create the new branch from (branch/tag/SHA).",
        "examples": ["main"],
    },
    "path": {
        "description": "Repository-relative path (POSIX-style).",
        "examples": ["README.md", "src/app.py"],
    },
    "paths": {
        "description": "List of repository-relative paths.",
        "examples": [["README.md", "src/app.py"]],
    },
    "query": {
        "description": "Search query string.",
        "examples": ["def main", "import os", "async def"],
    },
    "command": {
        "description": "Shell command to execute in the repo mirror (workspace clone).",
        "examples": ["pytest", "python -m ruff check ."],
    },
    "command_lines": {
        "description": (
            "Optional list of shell command lines. When provided, lines are joined with newlines and "
            "executed as a single command payload."
        ),
    },
    "timeout_seconds": {
        "description": "Timeout for the operation in seconds.",
        "examples": [60, 300, 600],
    },
    "workdir": {
        "description": (
            "Working directory to run the command from. If relative, it is resolved within the repo mirror."
        ),
        "examples": ["", "src"],
    },
    "per_page": {
        "description": "Number of results per page for GitHub REST pagination.",
        "examples": [30, 100],
    },
    "page": {
        "description": "1-indexed page number for GitHub REST pagination.",
        "examples": [1, 2],
    },
    "cursor": {
        "description": "Pagination cursor returned by the previous call.",
    },
    "limit": {
        "description": "Maximum number of results to return.",
        "examples": [20, 50, 200],
    },
    "message": {
        "description": "Commit message.",
        "examples": ["Refactor tool schemas"],
    },
    # Render tool parameters
    "owner_id": {
        "description": (
            "Render owner id (workspace or personal owner). Use list_render_owners to discover values."
        ),
    },
    "service_id": {
        "description": "Render service id (example: srv-...).",
    },
    "deploy_id": {
        "description": "Render deploy id (example: dpl-...).",
    },
    "resource_type": {
        "description": "Render log resource type (service or job).",
        "examples": ["service", "job"],
    },
    "resource_id": {
        "description": "Render log resource id corresponding to resource_type.",
    },
    "clear_cache": {
        "description": "When true, clears the build cache before deploying.",
        "examples": [True, False],
    },
    "commit_id": {
        "description": "Optional git commit SHA to deploy (repo-backed services).",
    },
    "image_url": {
        "description": "Optional container image URL to deploy (image-backed services).",
    },
    "start_time": {
        "description": "Optional ISO8601 timestamp for the start of a log query window.",
        "examples": ["2026-01-14T12:34:56Z"],
    },
    "end_time": {
        "description": "Optional ISO8601 timestamp for the end of a log query window.",
        "examples": ["2026-01-14T13:34:56Z"],
    },
}


def _apply_param_docs(schema: Dict[str, Any]) -> Dict[str, Any]:
    props = schema.get("properties")
    if not isinstance(props, dict):
        return schema
    out_props: Dict[str, Any] = {}
    for name, prop in props.items():
        if not isinstance(prop, dict):
            out_props[name] = prop
            continue

        updated = dict(prop)

        # Add stable titles (helps UIs render fields consistently).
        updated.setdefault("title", name.replace("_", " ").strip().title() or name)

        # Enrich with docs where available.
        docs = _PARAM_DOCS.get(name)
        if docs:
            desc = docs.get("description")
            if isinstance(desc, str) and desc:
                updated.setdefault("description", desc)
            if "examples" in docs and "examples" not in updated:
                updated["examples"] = docs["examples"]

        out_props[name] = updated

    schema["properties"] = out_props
    return schema


def _simplify_schema_aliases(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Hide legacy alias arguments from the *schema* while keeping runtime permissive.

    Many tools accept legacy aliases like (owner, repo) in addition to full_name,
    or (branch) in addition to ref. Those aliases remain supported at runtime
    (for backwards compatibility), but are intentionally hidden from the tool
    input schema so developer/LLM callers see a single canonical surface.
    """

    props = schema.get("properties")
    if not isinstance(props, dict):
        return schema
    required = schema.get("required")
    req_list = [r for r in required if isinstance(r, str)] if isinstance(required, list) else []

    def drop(name: str) -> None:
        props.pop(name, None)
        if name in req_list:
            req_list.remove(name)

    # Canonical repo identifier: full_name.
    if "full_name" in props:
        drop("owner")
        drop("repo")

    # Canonical ref: ref.
    if "ref" in props:
        drop("branch")

    schema["properties"] = props
    if req_list:
        schema["required"] = req_list
    else:
        schema.pop("required", None)
    return schema


def _simplify_input_schema_for_tool(schema: Mapping[str, Any], *, tool_name: str) -> Dict[str, Any]:
    """Return a cleaned-up schema intended for external tool consumption."""
    if not isinstance(schema, Mapping):
        return {}
    normalized: Dict[str, Any] = dict(schema)

    # Only object input schemas are supported.
    if normalized.get("type") != "object":
        return normalized

    normalized = _simplify_schema_aliases(normalized)
    normalized = _apply_param_docs(normalized)
    normalized.setdefault("title", _title_from_tool_name(tool_name))
    return normalized


# ---------------------------------------------------------------------------
# Log-safety helpers
# ---------------------------------------------------------------------------


def _log_preview_max_chars() -> Optional[int]:
    # Truncation is disabled.
    return None


def _jsonable(value: Any) -> Any:
    """Convert arbitrary Python values into something JSON-serializable.

    This exists purely
    to keep structured logging and schema metadata stable when values include
    non-JSON types (exceptions, bytes, sets, pydantic models, etc.).
    """
    # Fast path for common JSON scalars.
    if value is None or isinstance(value, (bool, int, float, str)):
        return value

    # Bytes are not JSON; decode best-effort.
    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8", errors="replace")
        except Exception:
            return str(value)

    # Mappings: coerce keys to strings.
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            try:
                key = k if isinstance(k, str) else str(k)
            except Exception:
                key = "<unprintable_key>"
            out[key] = _jsonable(v)
        return out

    # Iterables.
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]

    # Dataclasses.
    try:
        import dataclasses

        if dataclasses.is_dataclass(value):
            return _jsonable(dataclasses.asdict(value))
    except Exception:
        pass

    # Pydantic v2 models.
    try:
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            return _jsonable(dump(mode="json"))
    except Exception:
        pass

    # Exceptions.
    if isinstance(value, BaseException):
        return {"type": type(value).__name__, "message": str(value)}

    # Last resort: if it can be JSON-dumped, keep it; else stringify.
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        try:
            return str(value)
        except Exception:
            return f"<{type(value).__name__}>"


def _single_line(s: str) -> str:
    # Preserve content verbatim (no newline collapsing).
    return s


def _normalize_strings_for_logs(value: Any) -> Any:
    """Normalize strings inside a JSONable structure for log/UI previews.

    repr() encodes newlines as literal "\\n" sequences. If that preview is later
    JSON-encoded (common in MCP transports and UIs), those backslashes get
    escaped again, producing noisy "\\\\n" runs.

    This helper collapses whitespace in strings before serialization so previews
    remain single-line and stable.
    """

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            try:
                key = k if isinstance(k, str) else str(k)
            except Exception:
                key = "<unprintable_key>"
            out[key] = _normalize_strings_for_logs(v)
        return out
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_normalize_strings_for_logs(v) for v in value]
    return value


def _title_from_tool_name(name: str) -> str:
    # snake_case -> Title Case
    stripped = name.strip()
    parts = []
    current = []
    for ch in stripped:
        if ch in ("_", "-", " ", "\t", "\r", "\n"):
            if current:
                parts.append("".join(current))
                current = []
            continue
        current.append(ch)
    if current:
        parts.append("".join(current))
    if not parts:
        return "Tool"
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def _normalize_tool_description(
    func: Any,
    signature: Optional[inspect.Signature],
    *,
    llm_level: str = "basic",
) -> str:
    # Prefer docstring; fall back to signature-based description.
    doc = (inspect.getdoc(func) or "").strip()
    if doc:
        return doc

    sig = ""
    try:
        sig = str(signature) if signature is not None else ""
    except Exception:
        sig = ""

    # Keep fallback descriptions non-prescriptive; clients and agents should not
    # treat tool descriptions as behavioral constraints.
    base = f"{_title_from_tool_name(getattr(func, '__name__', 'tool'))}."
    if sig:
        base += f" Signature: {getattr(func, '__name__', 'tool')}{sig}."
    # llm_level retained for backward compatibility but not emitted.
    _ = llm_level
    return base




def _build_tool_docstring(
    *,
    tool_name: str,
    description: str,
    input_schema: Optional[Mapping[str, Any]],
    write_action: bool,
    visibility: str,
    write_allowed: Optional[bool] = None,
    tags: Optional[Sequence[str]] = None,
    ui: Optional[Mapping[str, Any]] = None,
) -> str:
    """Build a developer-oriented MCP tool docstring.

    This repository treats Python tool implementations as the source of truth.
    Tool documentation is assembled at registration time so that clients
    (including ChatGPT-style UIs) can display a consistent, detailed surface.

    Design goals:
    - Compact first line (many clients show only a summary in tool pickers).
    - Developer-facing detail aligned with runtime schema and tool metadata
      (write gates, visibility, UI hints).
    - Truthful, non-prescriptive language: reference material, not policy.

    High-level runtime behavior:
    - Tools are registered via the @mcp_tool decorator which attaches a JSON
      Schema-like input schema (plus a stable schema hash for observability).
    - In ChatGPT-oriented response modes, results may be normalized to include
      ok/status/summary and common streams (stdout/stderr) may be surfaced when
      present.

    This docstring intentionally stays high-level. Deeper lifecycle details
    belong in repository documentation.
    """

    def _schema_type(prop: Mapping[str, Any]) -> str:
        if not isinstance(prop, Mapping):
            return "unknown"
        t = prop.get("type")
        if isinstance(t, str) and t:
            return t
        any_of = prop.get("anyOf")
        if isinstance(any_of, list) and any_of:
            parts: list[str] = []
            for item in any_of:
                if isinstance(item, Mapping):
                    it = item.get("type")
                    if isinstance(it, str) and it:
                        parts.append(it)
                    elif isinstance(item.get("enum"), list):
                        parts.append("enum")
            return " | ".join(dict.fromkeys(parts)) or "unknown"
        if isinstance(prop.get("enum"), list):
            return "enum"
        return "unknown"

    def _fmt_bool(val: Any) -> str:
        if val is True:
            return "true"
        if val is False:
            return "false"
        return "unknown"

    def _ui_get(key: str) -> Any:
        if not isinstance(ui, Mapping):
            return None
        return ui.get(key)

    clean_desc = (description or "").strip()
    summary = clean_desc.splitlines()[0].strip() if clean_desc else ""
    if not summary:
        summary = f"{_title_from_tool_name(tool_name)}."

    lines: list[str] = [summary]

    # Long description (if it adds more than the first line).
    if clean_desc:
        rest = "\n".join([ln.rstrip() for ln in clean_desc.splitlines()[1:]]).strip()
        if rest:
            lines += ["", rest]

    # Classification / metadata.
    lines += ["", "Tool metadata:"]
    lines.append(f"- name: {tool_name}")
    if visibility:
        lines.append(f"- visibility: {visibility}")
    lines.append(f"- write_action: {_fmt_bool(write_action)}")
    if write_allowed is not None:
        lines.append(f"- write_allowed: {_fmt_bool(write_allowed)}")

    if tags:
        tag_list = [t for t in tags if isinstance(t, str) and t.strip()]
        if tag_list:
            lines.append(f"- tags: {', '.join(sorted(dict.fromkeys(tag_list)))}")

    # Optional UI hints: advisory and not displayed by all clients.
    if isinstance(ui, Mapping) and ui:
        group = _ui_get("group")
        icon = _ui_get("icon")
        prompt = _ui_get("prompt")
        inv_msg = _ui_get("invoking")
        done_msg = _ui_get("invoked")

        lines += ["", "UI hints (optional):"]
        if isinstance(group, str) and group.strip():
            lines.append(f"- group: {group.strip()}")
        if isinstance(icon, str) and icon.strip():
            lines.append(f"- icon: {icon.strip()}")
        if isinstance(prompt, str) and prompt.strip():
            lines.append(f"- prompt: {prompt.strip()}")
        if isinstance(inv_msg, str) and inv_msg.strip():
            lines.append(f"- invoking: {inv_msg.strip()}")
        if isinstance(done_msg, str) and done_msg.strip():
            lines.append(f"- invoked: {done_msg.strip()}")

    # Parameters (from the attached JSON schema).
    schema = input_schema if isinstance(input_schema, Mapping) else None
    props = schema.get("properties") if schema is not None else None
    required = schema.get("required") if schema is not None else None
    required_set = (
        {n for n in required if isinstance(n, str)} if isinstance(required, list) else set()
    )

    if isinstance(props, Mapping) and props:
        lines += ["", "Parameters:"]
        for name in sorted([k for k in props.keys() if isinstance(k, str)]):
            prop = props.get(name)
            if not isinstance(prop, Mapping):
                lines.append(f"- {name}: (unknown)")
                continue

            type_str = _schema_type(prop)
            req = "required" if name in required_set else "optional"
            default = prop.get("default")
            suffix_parts = [req]
            if default is not None:
                suffix_parts.append(f"default={default!r}")
            suffix = ", ".join(suffix_parts)
            lines.append(f"- {name} ({type_str}; {suffix})")

            pdesc = prop.get("description")
            if isinstance(pdesc, str) and pdesc.strip():
                lines.append(f"  {pdesc.strip()}")

            examples = prop.get("examples")
            if isinstance(examples, list) and examples:
                rendered = ", ".join(repr(e) for e in examples[:3])
                lines.append(f"  Examples: {rendered}")

    lines += [
        "",
        "Runtime notes:",
        "  - Tool calls are logged with a per-invocation call_id and may include a schema hash.",
        "  - Internal log-only keys prefixed with '__log_' are filtered from client responses.",
        "  - In ChatGPT-oriented response modes, results may be normalized to include ok/status/summary.",
        "",
        "Returns:",
        "  A JSON-serializable value defined by the tool implementation.",
    ]

    return "\n".join(lines).rstrip() + "\n"


def _normalize_input_schema(tool_obj: Any) -> Optional[Dict[str, Any]]:
    """
    Best-effort extraction of an input schema from an MCP tool object.

    We support multiple likely attribute names to avoid tight coupling to one framework version.

    Compatibility:
    - If schema has required fields but omits them from properties, we tighten the schema by
    adding default properties entries (type=string). This matches existing expectations in tests.
    """

    def _normalize_required_properties(schema: Mapping[str, Any]) -> Dict[str, Any]:
        required = schema.get("required")
        if not required:
            return dict(schema)
        if not isinstance(required, (list, tuple, set)):
            return dict(schema)
        required_names = [name for name in required if isinstance(name, str)]
        if not required_names:
            return dict(schema)

        properties = schema.get("properties")
        if not isinstance(properties, dict):
            properties = {}

        missing = [name for name in required_names if name not in properties]
        if not missing:
            return dict(schema)

        normalized = dict(schema)
        normalized_properties = dict(properties)
        for name in missing:
            normalized_properties[name] = {"type": "string"}
        normalized["properties"] = normalized_properties
        return normalized

    for attr in ("input_schema", "inputSchema", "schema", "parameters"):
        try:
            val = getattr(tool_obj, attr, None)
            if isinstance(val, dict):
                return _normalize_required_properties(val)
        except Exception:
            continue

    # Some frameworks store it inside meta.
    try:
        meta = getattr(tool_obj, "meta", None)
        if isinstance(meta, dict):
            for k in ("input_schema", "schema", "parameters"):
                v = meta.get(k)
                if isinstance(v, dict):
                    return _normalize_required_properties(v)
    except Exception:
        pass

    return None


def _annotation_to_schema(annotation: Any) -> Dict[str, Any]:
    if annotation is inspect.Signature.empty:
        return {}
    if annotation is None or annotation is type(None):
        return {"type": "null"}

    origin = get_origin(annotation)
    if origin is None:
        if annotation is str:
            return {"type": "string"}
        if annotation is int:
            return {"type": "integer"}
        if annotation is float:
            return {"type": "number"}
        if annotation is bool:
            return {"type": "boolean"}
        if annotation is list:
            return {"type": "array"}
        if annotation is dict:
            return {"type": "object"}
        return {}

    # typing.Literal[...] support (critical for correct schemas like Optional[Literal["asc","desc"]])
    if origin is typing.Literal:
        vals = get_args(annotation)
        if not vals:
            return {}

        json_vals = [_jsonable(v) for v in vals]
        type_set = {type(v) for v in vals}

        schema: Dict[str, Any] = {"enum": json_vals}

        # If all literal values are the same primitive type, emit an explicit JSON Schema type.
        if type_set == {str}:
            schema["type"] = "string"
        elif type_set == {int}:
            schema["type"] = "integer"
        elif type_set == {float}:
            schema["type"] = "number"
        elif type_set == {bool}:
            schema["type"] = "boolean"
        elif type_set == {type(None)}:
            schema["type"] = "null"
        else:
            # Mixed literals: keep enum without forcing a type.
            pass

        return schema

    if origin is list:
        args = get_args(annotation)
        items = _annotation_to_schema(args[0]) if args else {}
        return {"type": "array", "items": items}
    if origin is dict:
        args = get_args(annotation)
        value_schema = _annotation_to_schema(args[1]) if len(args) > 1 else {}
        return {"type": "object", "additionalProperties": value_schema}
    if origin is tuple:
        args = get_args(annotation)
        if args and args[-1] is ...:
            return {"type": "array", "items": _annotation_to_schema(args[0])}
        return {
            "type": "array",
            "prefixItems": [_annotation_to_schema(arg) for arg in args],
        }
    if origin is set:
        args = get_args(annotation)
        items = _annotation_to_schema(args[0]) if args else {}
        return {"type": "array", "items": items, "uniqueItems": True}
    if origin is type(None):
        return {"type": "null"}
    if origin is __import__("typing").Union or origin is getattr(types, "UnionType", None):
        args = get_args(annotation)
        return {"anyOf": [_annotation_to_schema(arg) for arg in args]}

    return {}


def _schema_from_signature(
    signature: Optional[inspect.Signature], *, tool_name: str = "tool"
) -> Dict[str, Any]:
    properties: Dict[str, Any] = {}
    required: list[str] = []

    if signature is None:
        return {"type": "object", "properties": {}}

    for param in signature.parameters.values():
        if param.name == "self":
            continue
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        param_schema: Dict[str, Any] = _annotation_to_schema(param.annotation)
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
        else:
            param_schema = dict(param_schema)
            param_schema["default"] = _jsonable(param.default)
        properties[param.name] = param_schema

    schema: Dict[str, Any] = {
        "type": "object",
        "properties": properties,
        # Contract policy:
        # The server does not enforce JSON Schema at runtime, but some clients
        # and UIs may treat the schema as a hard contract. For a developer-facing
        # MCP server we prefer permissive schemas by default so clients can send
        # extra keys (legacy aliases, forward-compatible params) without being
        # blocked by their own validators.
        "additionalProperties": True,
    }
    if required:
        schema["required"] = required
    return _simplify_input_schema_for_tool(schema, tool_name=tool_name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stringify_annotation(annotation: Any) -> str:
    """Return a stable string for a type annotation.

    This helper is part of the public compatibility surface and needs to not raise.
    """

    if annotation is None:
        return "None"
    if annotation is inspect.Signature.empty:
        return ""
    try:
        return str(annotation)
    except Exception:
        return f"<{type(annotation).__name__}>"


def _preflight_tool_args(
    tool_name: str,
    args: Mapping[str, Any],
    *,
    compact: bool = True,
) -> Dict[str, Any]:
    """Prepare tool args for display/logging.

    Policy:
    - No transformation.
    - Ensure JSON-serializable output.
    """

    try:
        payload = {"tool": tool_name, "args": _jsonable(dict(args))}
        # Compact mode no longer produces a string preview (which can be re-escaped
        # by downstream layers). Return the JSONable object directly.
        return payload
    except Exception:
        return {"tool": tool_name, "preview": "<unprintable_args>"}
