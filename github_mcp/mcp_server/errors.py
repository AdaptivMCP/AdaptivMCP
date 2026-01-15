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

import os
import traceback
from typing import Any, Dict, Optional


def _redact_tokens(text: str) -> str:
    """Return text unchanged.

    This server is intended to be self-hosted in environments where operators
    may prefer full-fidelity logs and error payloads without credential
    redaction/masking.
    """

    return text


def _single_line(s: str) -> str:
    # Ensure messages are stable and don't introduce embedded newlines into logs/UI.
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = " ".join(s.split())
    return s


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
        return lines
    except Exception:
        return [f"{exc.__class__.__name__}: {_single_line(str(exc))}"]


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
            "This tool performs write operations and requires explicit approval.",
            "Approve the write action in your client and retry.",
        ]
    return [
        "Retry once. If the error persists, check provider logs for the corresponding request.",
    ]


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

    message = _single_line(str(exc) or exc.__class__.__name__)
    category, code, retryable = _categorize_exception(exc)

    include_tb = os.environ.get("GITHUB_MCP_INCLUDE_TRACEBACK", "true").strip().lower() in (
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
        debug["args"] = {k: _single_line(str(v))[:500] for k, v in list(args.items())[:50]}

    detail: Dict[str, Any] = {
        "message": message,
        "category": category,
        "code": code,
        "retryable": bool(retryable),
        "context": {
            "context": context,
            "path": path,
            "tool_surface": tool_surface,
            "routing_hint": routing_hint,
            "request": request,
        },
        "help": _default_help(category),
        "debug": debug,
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
        detail["context"]["tool_descriptor_text"] = _single_line(tool_descriptor_text)[:2000]
    if trace is not None:
        detail["trace"] = trace

    return {"error": message, "error_detail": detail}


def _exception_trace(exc: BaseException) -> str:
    """Optional helper: stringify a traceback when you explicitly want it."""

    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return f"{exc.__class__.__name__}: {_single_line(str(exc))}"
