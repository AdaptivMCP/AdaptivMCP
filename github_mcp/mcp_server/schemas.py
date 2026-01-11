"""Schema + metadata helpers."""

from __future__ import annotations

import inspect
import json
import os
import re
import types
import typing
from typing import Any, Dict, Mapping, Optional, get_args, get_origin


# ---------------------------------------------------------------------------
# Log-safety helpers
# ---------------------------------------------------------------------------


def _log_preview_max_chars() -> Optional[int]:
    """Max characters allowed in log previews.

    This is intentionally dynamic so tests (and operators) can adjust the limit
    via environment variables without requiring a module reload.
    """

    # 0 (or negative) disables truncation.
    raw = os.environ.get("GITHUB_MCP_LOG_PREVIEW_MAX_CHARS", "0")
    try:
        limit = int(str(raw).strip())
    except Exception:
        limit = 0
    if limit <= 0:
        return None
    return max(128, limit)


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
    """Return a stable single-line string for logs."""
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(s.split())


def _title_from_tool_name(name: str) -> str:
    # snake_case -> Title Case
    parts = re.split(r"[_\-\s]+", name.strip())
    parts = [p for p in parts if p]
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

    base = f"{_title_from_tool_name(getattr(func, '__name__', 'tool'))}."
    if sig:
        base += f" Signature: {getattr(func, '__name__', 'tool')}{sig}."
    base += f" LLM level: {llm_level}."
    return base


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


def _schema_from_signature(signature: Optional[inspect.Signature]) -> Dict[str, Any]:
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
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _truncate_str(s: str) -> str:
    max_chars = _log_preview_max_chars()
    if not max_chars:
        return s
    if len(s) <= max_chars:
        return s
    # Leave room for a single ellipsis.
    return s[: max_chars - 1] + "…"


def _normalize_and_truncate(s: str) -> str:
    return _truncate_str(_single_line(s))


def _format_tool_args_preview(args: Mapping[str, Any]) -> str:
    """Stable preview of tool args for logs.

    Uses repr() to avoid heavy JSON escaping that can trigger false downstream blocks.
    """
    try:
        jsonable_args = _jsonable(dict(args))
        raw = repr(jsonable_args)
        return _normalize_and_truncate(raw)
    except Exception:
        try:
            return _normalize_and_truncate(str(args))
        except Exception:
            return "<unprintable_args>"


# ---------------------------------------------------------------------------
# Backwards-compatible helpers
# ---------------------------------------------------------------------------


def _stringify_annotation(annotation: Any) -> str:
    """Return a stable string for a type annotation.

    This helper is part of the public compatibility surface and must never raise.
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
        if compact:
            # Use repr() rather than JSON to avoid heavy escaping and to preserve
            # argument order.
            raw = repr(payload)
            return {"tool": tool_name, "preview": _normalize_and_truncate(raw)}
        return payload
    except Exception:
        return {"tool": tool_name, "preview": "<unprintable_args>"}
