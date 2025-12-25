"""
Schema + metadata helpers.

Project policy:
- No custom token redaction.
- Still enforce JSON-serializable metadata and bounded previews to keep logs stable.
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
    """
    for attr in ("input_schema", "inputSchema", "schema", "parameters"):
        try:
            val = getattr(tool_obj, attr, None)
            if isinstance(val, dict):
                return val
        except Exception:
            continue

    # Some frameworks store it inside meta.
    try:
        meta = getattr(tool_obj, "meta", None)
        if isinstance(meta, dict):
            for k in ("input_schema", "schema", "parameters"):
                v = meta.get(k)
                if isinstance(v, dict):
                    return v
    except Exception:
        pass

    return None


def _truncate_str(s: str) -> str:
    if len(s) <= _MAX_STR_LEN:
        return s
    return s[: _MAX_STR_LEN] + "…(truncated)"


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
        return _truncate_str(value)

    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= _MAX_DICT_ITEMS:
                out["…"] = f"(truncated after {_MAX_DICT_ITEMS} keys)"
                break
            key = str(k)
            out[_truncate_str(key)] = _sanitize_metadata_value(v, _depth=_depth + 1)
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
        return _truncate_str(str(value))
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
        return _truncate_str(raw)
    except Exception:
        # Worst-case fallback
        try:
            return _truncate_str(str(args))
        except Exception:
            return "<unprintable_args>"