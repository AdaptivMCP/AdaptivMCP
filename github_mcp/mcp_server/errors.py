"""Error payload construction.

The MCP server historically returned a single string error message for maximum
compatibility with thin clients.

This module keeps that compatibility surface (top-level "error" string) while
adding structured diagnostics in "error_detail".

The intent is to make failures understandable for:
- non-technical users (clear message + next steps), and
- developers/operators (category, retryability, request context, traceback).

Returned shape:

    {
      "error": "<single line message>",
      "error_detail": {
        "message": "<same message>",
        "category": "validation|auth|rate_limited|not_found|conflict|internal|...",
        "code": "<stable-ish identifier>",
        "retryable": bool,
        "context": { ... },
        "help": ["...", ...],
        "debug": { ... }
      }
    }

The top-level "error" remains the primary compatibility surface.
"""

from __future__ import annotations

import hashlib
import os
import traceback
from typing import Any, Dict, Optional

from github_mcp.redaction import redact_any, redact_text


def _redact_tokens(text: str) -> str:
    """Redact common secrets from error strings.

    In hosted connector environments, emitting raw tokens/keys can cause the
    upstream platform to block tool outputs. We therefore redact by default.
    """

    return redact_text(text)


def _single_line(s: str) -> str:
    # Ensure messages are stable and don't introduce embedded newlines into logs/UI.
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = " ".join(s.split())
    return s

_SENSITIVE_ARG_KEYS = {
    'patch',
    'content',
    'body',
    'text',
    'data',
    'replacement',
    'old',
    'new',
}

def _safe_arg_value(key: str, value: Any) -> Any:
    """Return a compact, redacted representation of an arg value.

    Some tool args (notably patches and file contents) can be very large or
    contain token-like strings that trigger upstream safety filters. We avoid
    echoing these values back in error payloads.
    """
    try:
        k = (key or '').strip().lower()
    except Exception:
        k = str(key)

    if k in _SENSITIVE_ARG_KEYS:
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            b = bytes(value)
            digest = hashlib.sha256(b).hexdigest()
            return f'<omitted bytes len={len(b)} sha256={digest}>'
        s = str(value)
        digest = hashlib.sha256(s.encode('utf-8', errors='replace')).hexdigest()
        return f'<omitted len={len(s)} sha256={digest}>'

    # Default: single-line + bounded preview + token redaction.
    s = _single_line(str(value))
    max_chars = int(os.environ.get('GITHUB_MCP_ERROR_ARG_MAX_CHARS', '500') or '500')
    if max_chars > 0 and len(s) > max_chars:
        s = s[: max(0, max_chars - 1)] + '…'
    return _redact_tokens(s)


def _safe_traceback_lines(exc: BaseException, *, max_lines: int) -> list[str]:
    try:
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        lines: list[str] = []
        for chunk in tb:
            for ln in chunk.splitlines():
                if ln.strip():
                    lines.append(ln.rstrip())

        if max_lines > 0 and len(lines) > max_lines:
            head = lines[: max_lines // 2]
            tail = lines[-(max_lines - len(head)) :]
            omitted = len(lines) - (len(head) + len(tail))
            lines = head + [f"… ({omitted} lines omitted) …"] + tail
        return [redact_text(ln) for ln in lines]
    except Exception:
        return [redact_text(f"{exc.__class__.__name__}: {_single_line(str(exc))}")]


def _is_render_runtime() -> bool:
    """Best-effort detection for Render deployments.

    Render sets a number of standard environment variables for running services.
    We use these signals to adjust provider-facing defaults (e.g., avoid emitting
    verbose tracebacks into hosted logs unless explicitly requested).
    """

    return any(
        os.environ.get(name)
        for name in (
            "RENDER",
            "RENDER_SERVICE_ID",
            "RENDER_SERVICE_NAME",
            "RENDER_EXTERNAL_URL",
            "RENDER_INSTANCE_ID",
            "RENDER_GIT_COMMIT",
        )
    )


def _categorize_exception(exc: BaseException) -> tuple[str, str, bool]:
    """Return (category, code, retryable)."""

    # Respect explicit attributes (used by UsageError and similar).
    try:
        category = getattr(exc, "category", None)
        code = getattr(exc, "code", None)
        retryable = getattr(exc, "retryable", None)
        if isinstance(category, str) and category.strip():
            return category.strip(), str(code or "error").strip() or "error", bool(retryable)
    except Exception:
        pass

    # Avoid importing heavier modules at import time.
    try:
        from github_mcp import exceptions as mcp_exceptions  # type: ignore

        if isinstance(exc, getattr(mcp_exceptions, "ToolPreflightValidationError", ())):
            return "validation", "tool_preflight_validation", False
        if isinstance(exc, getattr(mcp_exceptions, "GitHubAuthError", ())):
            return "auth", "github_auth", False
        if isinstance(exc, getattr(mcp_exceptions, "RenderAuthError", ())):
            return "auth", "render_auth", False
        if isinstance(exc, getattr(mcp_exceptions, "GitHubNotFoundError", ())):
            return "not_found", "github_not_found", False
        if isinstance(exc, getattr(mcp_exceptions, "GitHubRateLimitError", ())):
            return "rate_limited", "github_rate_limited", True
        if isinstance(exc, getattr(mcp_exceptions, "RenderRateLimitError", ())):
            return "rate_limited", "render_rate_limited", True
        if isinstance(exc, getattr(mcp_exceptions, "WriteApprovalRequiredError", ())):
            return "write_approval_required", "write_approval_required", False
    except Exception:
        pass

    if isinstance(exc, (ValueError, TypeError)):
        return "validation", "invalid_arguments", False

    return "internal", "internal_error", False


def _default_help(category: str) -> list[str]:
    if category == "validation":
        return [
            "Check the tool arguments and try again.",
            "If you are calling this via HTTP, ensure the JSON payload matches the tool schema.",
        ]
    if category == "auth":
        return [
            "Verify the required credentials are configured in environment variables.",
            "For GitHub: set one of GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, or GITHUB_OAUTH_TOKEN.",
            "For Render: set RENDER_API_KEY or RENDER_API_TOKEN.",
        ]
    if category == "rate_limited":
        return [
            "Retry after a short delay.",
            "If this persists, reduce call rate or use a token with higher rate limits.",
        ]
    if category == "write_approval_required":
        return [
            "This tool can modify remote state and requires confirmation in your client.",
            "Confirm/approve the write action in your client, then retry the same call.",
        ]
    # Avoid imperative instructions that can cause LLM clients to loop.
    # Keep guidance informational and direct operators to logs/telemetry.
    return [
        "Review provider logs/telemetry for the corresponding request for details.",
        "If this is transient, re-run the call once with the same inputs.",
    ]


def _disposition_from_category(category: str) -> tuple[str, bool]:
    """Return (disposition, requires_confirmation).

    This field exists to help LLM agents distinguish ordinary execution errors
    (bad inputs, upstream failures) from flows that require an explicit user
    confirmation in the client (e.g. write-capable tools).
    """

    if category == "write_approval_required":
        return "requires_confirmation", True
    return "error", False


def _structured_tool_error(
    exc: BaseException,
    *,
    context: Optional[str] = None,
    path: Optional[str] = None,
    tool_descriptor: Optional[Dict[str, Any]] = None,
    tool_descriptor_text: Optional[str] = None,
    tool_surface: Optional[str] = None,
    routing_hint: Optional[Dict[str, Any]] = None,
    request: Optional[Dict[str, Any]] = None,
    trace: Optional[Dict[str, Any]] = None,
    args: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert any exception into a structured, user-facing error payload.

    Compatibility contract:
    - Always returns {"error": "<message>"} (single line).
    - Adds "error_detail" for clients that want structured diagnostics.
    """

    message = _redact_tokens(_single_line(str(exc) or exc.__class__.__name__))
    category, code, retryable = _categorize_exception(exc)
    disposition, requires_confirmation = _disposition_from_category(category)

    # Hosted providers (Render) already surface stack traces in platform logs when
    # `exc_info` is used. Default to *not* embedding tracebacks in tool payloads
    # unless explicitly enabled.
    include_tb_raw = os.environ.get("GITHUB_MCP_INCLUDE_TRACEBACK")
    if include_tb_raw is None:
        include_tb = not _is_render_runtime()
    else:
        include_tb = str(include_tb_raw).strip().lower() in (
            "1",
            "true",
            "t",
            "yes",
            "y",
            "on",
        )
    max_tb_lines = int(os.environ.get("GITHUB_MCP_TRACEBACK_MAX_LINES", "60") or "60")

    debug: Dict[str, Any] = {
        "exception_type": exc.__class__.__name__,
    }
    if include_tb:
        debug["traceback"] = _safe_traceback_lines(exc, max_lines=max_tb_lines)

    if args:
        # Keep args compact and single-line.
        debug["args"] = {k: _safe_arg_value(str(k), v) for k, v in list(args.items())[:50]}

    detail: Dict[str, Any] = {
        "message": message,
        "category": category,
        "code": code,
        "retryable": bool(retryable),
        "disposition": disposition,
        "requires_confirmation": bool(requires_confirmation),
        "context": {
            "context": context,
            "path": path,
            "tool_surface": tool_surface,
            "routing_hint": redact_any(routing_hint) if routing_hint is not None else None,
            "request": redact_any(request) if request is not None else None,
        },
        "help": _default_help(category),
        "debug": redact_any(debug),
    }

    # Preserve richer details emitted by higher-level exceptions.
    try:
        details = getattr(exc, "details", None)
        if isinstance(details, dict) and details:
            detail["details"] = details
    except Exception:
        pass

    try:
        hint = getattr(exc, "hint", None)
        if isinstance(hint, str) and hint.strip():
            help_list = list(detail.get("help") or [])
            help_list.insert(0, hint.strip())
            detail["help"] = help_list[:10]
    except Exception:
        pass

    if tool_descriptor is not None:
        detail["context"]["tool_descriptor"] = tool_descriptor
    if tool_descriptor_text is not None:
        detail["context"]["tool_descriptor_text"] = _redact_tokens(
            _single_line(tool_descriptor_text)[:2000]
        )
    if trace is not None:
        detail["trace"] = redact_any(trace)

    return {"status": "error", "ok": False, "error": message, "error_detail": redact_any(detail)}


def _exception_trace(exc: BaseException) -> str:
    """Optional helper: stringify a traceback when you explicitly want it."""

    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return f"{exc.__class__.__name__}: {_single_line(str(exc))}"
