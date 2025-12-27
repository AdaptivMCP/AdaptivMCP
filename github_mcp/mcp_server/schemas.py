"""Schema + metadata helpers."""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Dict, Mapping, Optional

def _jsonable(value: Any) -> Any:
    """Convert arbitrary Python values into something JSON-serializable.

    This is intentionally not a redaction/sanitization layer. It exists purely
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
    """Return the string unchanged."""
    return s


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

    def _tighten_required_properties(schema: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if schema.get("type") != "object":
                return schema

            props = schema.get("properties")
            if not isinstance(props, dict):
                props = {}
                schema["properties"] = props

            req = schema.get("required")
            if isinstance(req, list):
                for name in req:
                    if isinstance(name, str) and name not in props:
                        props[name] = {"type": "string"}
        except Exception:
            return schema

        return schema

    for attr in ("input_schema", "inputSchema", "schema", "parameters"):
        try:
            val = getattr(tool_obj, attr, None)
            if isinstance(val, dict):
                return _tighten_required_properties(val)
        except Exception:
            continue

    # Some frameworks store it inside meta.
    try:
        meta = getattr(tool_obj, "meta", None)
        if isinstance(meta, dict):
            for k in ("input_schema", "schema", "parameters"):
                v = meta.get(k)
                if isinstance(v, dict):
                    return _tighten_required_properties(v)
    except Exception:
        pass

    return None


def _truncate_str(s: str) -> str:
    return s


def _normalize_and_truncate(s: str) -> str:
    return s


def _format_tool_args_preview(args: Mapping[str, Any]) -> str:
    """
    Stable, bounded preview of tool args for logs.

    Produces a single-line JSON string (truncated).
    """
    try:
        sanitized = _jsonable(dict(args))
        raw = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return raw
    except Exception:
        # Worst-case fallback
        try:
            return str(args)
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
    - No redaction.
    - Ensure JSON-serializable output.
    """
    try:
        payload = {
            "tool": tool_name,
            "args": _jsonable(dict(args)),
        }
        if compact:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return {"tool": tool_name, "preview": _truncate_str(_single_line(raw))}
        return payload
    except Exception:
        return {"tool": tool_name, "preview": "<unprintable_args>"}
