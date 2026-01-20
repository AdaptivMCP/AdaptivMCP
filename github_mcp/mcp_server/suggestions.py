"""Helpers for turning common tool invocation mistakes into actionable warnings.

These warnings are intended to help LLM callers self-correct when they:
  - call a non-existent tool name, or
  - call an existing tool with invalid / mismatched argument names.

The helpers are best-effort and must never raise.
"""

from __future__ import annotations

import difflib
import inspect
from typing import Any, Iterable, Mapping


def _norm_token(value: str) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def suggest_best_name(requested: str, options: Iterable[str], *, cutoff: float = 0.6) -> str | None:
    """Return the closest matching option to `requested`, if any."""

    try:
        requested_n = _norm_token(requested)
        opt_list = [str(o) for o in options if o is not None and str(o).strip()]
        if not opt_list:
            return None

        # difflib works on sequences of strings; we normalize both sides but return
        # the original option for display.
        normalized_to_original: dict[str, str] = {}
        normalized: list[str] = []
        for o in opt_list:
            n = _norm_token(o)
            normalized_to_original.setdefault(n, o)
            normalized.append(n)

        matches = difflib.get_close_matches(requested_n, normalized, n=1, cutoff=float(cutoff))
        if not matches:
            return None
        return normalized_to_original.get(matches[0])
    except Exception:
        return None


def expected_args_from_signature(signature: inspect.Signature | None) -> dict[str, Any]:
    """Return a stable summary of expected argument names for a callable."""

    out: dict[str, Any] = {
        "all": [],
        "required": [],
        "optional": [],
        "accepts_var_kwargs": False,
        "accepts_var_args": False,
    }

    if signature is None:
        return out

    try:
        params = list(signature.parameters.values())
        accepts_var_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
        accepts_var_args = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
        out["accepts_var_kwargs"] = accepts_var_kwargs
        out["accepts_var_args"] = accepts_var_args

        names: list[str] = []
        required: list[str] = []
        optional: list[str] = []
        for p in params:
            if p.name in {"self", "cls"}:
                continue
            if p.kind in {inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL}:
                continue
            names.append(p.name)
            if p.default is inspect._empty:
                required.append(p.name)
            else:
                optional.append(p.name)

        out["all"] = names
        out["required"] = required
        out["optional"] = optional
        return out
    except Exception:
        return out


def build_unknown_tool_payload(tool_name: str, available_tools: Iterable[str]) -> dict[str, Any]:
    """Return a structured error payload for an unknown tool with suggestions."""

    available = [str(t) for t in available_tools if t is not None and str(t).strip()]
    suggestion = suggest_best_name(tool_name, available)

    warnings: list[str] = []
    if suggestion:
        warnings.append(f"Unknown tool {tool_name!r}. Did you mean {suggestion!r}?")
    elif available:
        # Keep this bounded; callers can always hit /tools for the full list.
        sample = ", ".join(sorted(available)[:15])
        warnings.append(f"Unknown tool {tool_name!r}. Available tools include: {sample}")
    else:
        warnings.append(f"Unknown tool {tool_name!r}.")

    payload: dict[str, Any] = {
        "status": "error",
        "ok": False,
        "error": f"Unknown tool {tool_name!r}.",
        "category": "not_found",
        "warnings": warnings,
    }
    if suggestion:
        payload["suggested_tool"] = suggestion
    return payload


def augment_structured_error_for_bad_args(
    structured_error: Any,
    *,
    tool_name: str,
    signature: inspect.Signature | None,
    provided_kwargs: Mapping[str, Any] | None,
    exc: BaseException,
) -> Any:
    """Add argument-name guidance to a structured error when possible."""

    if not isinstance(structured_error, dict):
        return structured_error
    if signature is None or not isinstance(exc, TypeError):
        return structured_error
    if provided_kwargs is None:
        provided_kwargs = {}

    try:
        expected = expected_args_from_signature(signature)
        expected_all = set(expected.get("all") or [])
        accepts_var_kwargs = bool(expected.get("accepts_var_kwargs"))

        provided_keys = [str(k) for k in provided_kwargs.keys() if k is not None]
        unknown = [k for k in provided_keys if (not accepts_var_kwargs) and k not in expected_all]
        missing = [k for k in (expected.get("required") or []) if k not in provided_keys]

        warnings: list[str] = []
        if unknown:
            per_key: list[str] = []
            for key in unknown[:10]:
                guess = suggest_best_name(key, expected_all)
                if guess and guess != key:
                    per_key.append(f"{key!r} -> {guess!r}")
            if per_key:
                warnings.append(
                    f"Invalid argument name(s) for {tool_name}: {', '.join(unknown)}. Closest matches: {', '.join(per_key)}"
                )
            else:
                warnings.append(f"Invalid argument name(s) for {tool_name}: {', '.join(unknown)}")

        if missing:
            warnings.append(f"Missing required argument(s) for {tool_name}: {', '.join(missing)}")

        # Always include the authoritative arg list when we have it.
        req = ", ".join(expected.get("required") or []) or "(none)"
        opt = ", ".join(expected.get("optional") or []) or "(none)"
        warnings.append(f"Valid args for {tool_name}: required=[{req}], optional=[{opt}]")

        if warnings:
            structured_error.setdefault("warnings", [])
            if isinstance(structured_error["warnings"], list):
                structured_error["warnings"].extend(warnings)
            else:
                structured_error["warnings"] = warnings

        # Also add machine-readable hints.
        detail = structured_error.get("error_detail")
        if isinstance(detail, dict):
            details = detail.get("details")
            if not isinstance(details, dict):
                details = {}
                detail["details"] = details
            details.setdefault("expected_args", expected)
            if unknown:
                details.setdefault("unknown_args", unknown)
            if missing:
                details.setdefault("missing_args", missing)
    except Exception:
        return structured_error

    return structured_error

