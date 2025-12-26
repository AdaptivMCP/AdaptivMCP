"""
Schema + metadata helpers.

Project policy:
- No custom token redaction.
- Still enforce JSON-serializable metadata and bounded previews to keep logs stable.

Note on log stability:
- Tool args and metadata are frequently embedded into log lines and UI previews.
- To prevent accidental multi-line log entries, we normalize string values to a single line
  (\r/\n/\t collapse + control-char removal) before truncation.
"""

from __future__ import annotations

import inspect
import json
import re
from typing import Any, Dict, Mapping, Optional


_MAX_STR_LEN = 2000
_MAX_LIST_ITEMS = 100
_MAX_DICT_ITEMS = 200
_MAX_DEPTH = 6


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _single_line(s: str) -> str:
    """Normalize a string for safe log/UI embedding."""
    # Normalize newlines/tabs to spaces
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # Drop remaining control chars
    s = _CONTROL_CHARS_RE.sub("", s)
    # Collapse whitespace runs
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
    if len(s) <= _MAX_STR_LEN:
        return s
    return s[:_MAX_STR_LEN] + "…(truncated)"


def _normalize_and_truncate(s: str) -> str:
    """Normalize strings without scanning unbounded payloads."""
    if len(s) > _MAX_STR_LEN:
        head = s[:_MAX_STR_LEN]
        return _single_line(head) + "…(truncated)"
    return _single_line(s)


def _sanitize_metadata_value(value: Any, *, _depth: int = 0) -> Any:
    """
    Convert arbitrary values into a JSON-serializable, bounded structure.

    NOTE: No redaction is applied; only type normalization + truncation.
    """
    if _depth > _MAX_DEPTH:
        return "…(max_depth)"

    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _normalize_and_truncate(value)

    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_DICT_ITEMS:
                out["…"] = f"(truncated after {_MAX_DICT_ITEMS} keys)"
                break
            key = _truncate_str(_single_line(str(k)))
            out[key] = _sanitize_metadata_value(v, _depth=_depth + 1)
        return out

    if isinstance(value, (list, tuple, set)):
        out_list = []
        for i, item in enumerate(value):
            if i >= _MAX_LIST_ITEMS:
                out_list.append(f"…(truncated after {_MAX_LIST_ITEMS} items)")
                break
            out_list.append(_sanitize_metadata_value(item, _depth=_depth + 1))
        return out_list

    # Fallback: stringify
    try:
        return _truncate_str(_single_line(str(value)))
    except Exception:
        return f"<{type(value).__name__}>"


def _format_tool_args_preview(args: Mapping[str, Any]) -> str:
    """
    Stable, bounded preview of tool args for logs.

    Produces a single-line JSON string (truncated).
    """
    try:
        sanitized = _sanitize_metadata_value(dict(args))
        raw = json.dumps(sanitized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return _truncate_str(_single_line(raw))
    except Exception:
        # Worst-case fallback
        try:
            return _truncate_str(_single_line(str(args)))
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
    - Ensure JSON-serializable, bounded output.
    """
    try:
        payload = {
            "tool": tool_name,
            "args": _sanitize_metadata_value(dict(args)),
        }
        if compact:
            raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            return {"tool": tool_name, "preview": _truncate_str(_single_line(raw))}
        return payload
    except Exception:
        return {"tool": tool_name, "preview": "<unprintable_args>"}
