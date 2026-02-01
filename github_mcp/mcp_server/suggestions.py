"""Helpers for turning common tool invocation mistakes into actionable warnings.

These warnings are intended to help callers self-correct when they:
  - call a non-existent tool name, or
  - call an existing tool with invalid / mismatched argument names.

The helpers are best-effort and must never raise.
"""

from __future__ import annotations

import difflib
import inspect
from collections.abc import Iterable, Mapping
from typing import Any


def _norm_token(value: str) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _similarity(a: str, b: str) -> float:
    """Return a stable similarity score in [0, 1].

    This is intentionally simple and dependency-free.
    """

    try:
        return difflib.SequenceMatcher(None, a, b).ratio()
    except Exception:
        return 0.0


def rank_names(requested: str, options: Iterable[str]) -> list[tuple[float, str]]:
    """Return candidate options ranked by similarity to `requested`.

    The output is a list of (score, original_name), sorted descending by score.
    """

    try:
        requested_n = _norm_token(requested)
        opt_list = [str(o) for o in options if o is not None and str(o).strip()]
        ranked: list[tuple[float, str]] = []
        for o in opt_list:
            score = _similarity(requested_n, _norm_token(o))
            ranked.append((float(score), o))
        ranked.sort(key=lambda t: (-t[0], t[1]))
        return ranked
    except Exception:
        return []


def suggest_close_matches(
    requested: str,
    options: Iterable[str],
    *,
    cutoff: float = 0.6,
    max_suggestions: int = 5,
) -> list[str]:
    """Return up to `max_suggestions` close matches to `requested`.

    Matches are ordered by similarity (descending).
    """

    ranked = rank_names(requested, options)
    if not ranked:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for score, name in ranked:
        if score < float(cutoff):
            break
        if name in seen:
            continue
        out.append(name)
        seen.add(name)
        if len(out) >= int(max_suggestions):
            break
    return out


def suggest_best_name(
    requested: str, options: Iterable[str], *, cutoff: float = 0.6
) -> str | None:
    """Return the closest matching option to `requested`, if any.

    This is retained for backward compatibility; prefer `suggest_close_matches`.
    """

    matches = suggest_close_matches(
        requested, options, cutoff=cutoff, max_suggestions=1
    )
    return matches[0] if matches else None


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
        accepts_var_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params
        )
        accepts_var_args = any(
            p.kind == inspect.Parameter.VAR_POSITIONAL for p in params
        )
        out["accepts_var_kwargs"] = accepts_var_kwargs
        out["accepts_var_args"] = accepts_var_args

        names: list[str] = []
        required: list[str] = []
        optional: list[str] = []
        for p in params:
            if p.name in {"self", "cls"}:
                continue
            if p.kind in {
                inspect.Parameter.VAR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.POSITIONAL_ONLY,
            }:
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


def _high_confidence_single_match(
    ranked: list[tuple[float, str]], matches: list[str]
) -> str | None:
    """Return a single suggested tool only when the signal is strong.

    Tool runtimes can over-anchor on a single suggestion; we only return one
    when the requested name is extremely close and unambiguous.
    """

    if not matches or not ranked:
        return None
    if len(matches) != 1:
        return None

    best_score = ranked[0][0]
    if best_score < 0.92:
        return None

    # If we have a runner-up with a close score, avoid suggesting a single tool.
    if len(ranked) >= 2:
        gap = best_score - float(ranked[1][0])
        if gap < 0.08:
            return None

    return matches[0]


def build_unknown_tool_payload(
    tool_name: str, available_tools: Iterable[str]
) -> dict[str, Any]:
    """Return a structured error payload for an unknown tool with suggestions.

    Key behavior:
    - Prefer *ranked* candidates (similarity-based) rather than an alphabetical
      sample, so suggestions vary by user intent.
    - Provide multiple close matches to reduce the chance of "getting stuck" on
      a single repeated tool.
    - Only emit `suggested_tool` when the match is high-confidence.
    """

    available = [str(t) for t in available_tools if t is not None and str(t).strip()]
    ranked = rank_names(tool_name, available)
    close_matches = suggest_close_matches(
        tool_name, available, cutoff=0.66, max_suggestions=5
    )
    single = _high_confidence_single_match(ranked, close_matches)

    warnings: list[str] = []
    if single:
        warnings.append(f"Did you mean {single!r}?")
    elif close_matches:
        rendered = ", ".join(repr(x) for x in close_matches)
        warnings.append(
            f"Close matches: {rendered}. If none fit, call GET /tools to discover the full catalog."
        )
    elif available:
        # Keep this bounded; callers can always hit /tools for the full list.
        top = ", ".join(repr(name) for _score, name in ranked[:15])
        warnings.append(
            f"Most similar available tools: {top}. (For the full list, call GET /tools.)"
        )
    else:
        warnings.append("No tools are registered on this server.")

    payload: dict[str, Any] = {
        "status": "error",
        "ok": False,
        "error": f"Unknown tool {tool_name!r}.",
        "category": "not_found",
        "warnings": warnings,
    }

    if close_matches:
        payload["suggested_tools"] = close_matches
    if single:
        payload["suggested_tool"] = single

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
        unknown = [
            k
            for k in provided_keys
            if (not accepts_var_kwargs) and k not in expected_all
        ]
        missing = [
            k for k in (expected.get("required") or []) if k not in provided_keys
        ]

        warnings: list[str] = []
        if unknown:
            per_key: list[str] = []
            for key in unknown[:10]:
                guesses = suggest_close_matches(
                    key, expected_all, cutoff=0.66, max_suggestions=3
                )
                if guesses and guesses[0] != key:
                    per_key.append(f"{key!r} -> {', '.join(repr(g) for g in guesses)}")
            if per_key:
                warnings.append(
                    f"Invalid argument name(s) for {tool_name}: {', '.join(unknown)}. Closest matches: {', '.join(per_key)}"
                )
            else:
                warnings.append(
                    f"Invalid argument name(s) for {tool_name}: {', '.join(unknown)}"
                )

        if missing:
            warnings.append(
                f"Missing required argument(s) for {tool_name}: {', '.join(missing)}"
            )

        # Always include the authoritative arg list when we have it.
        req = ", ".join(expected.get("required") or []) or "(none)"
        opt = ", ".join(expected.get("optional") or []) or "(none)"
        warnings.append(
            f"Valid args for {tool_name}: required=[{req}], optional=[{opt}]"
        )

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
