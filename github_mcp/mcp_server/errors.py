"""
Structured error model for Adaptiv MCP.

Requirements:
- Machine readable: stable fields for programmatic handling.
- User readable: clear, detailed messages.
- No custom redaction layer is applied here (per project policy).
"""

from __future__ import annotations

import re
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from github_mcp.exceptions import GitHubRateLimitError


@dataclass
class AdaptivToolError(Exception):
    """
    A structured error intended to be surfaced to the user and to automation.

    Fields:
      - code: stable identifier (snake_case).
      - message: user-facing core message.
      - category: broad bucket: permission|validation|upstream|runtime|configuration|not_found|conflict|timeout
      - origin: subsystem that produced the error.
      - retryable: whether retry is likely to succeed without changes.
      - details: JSON-serializable object for debugging.
      - hint: optional next step guidance.
    """

    code: str
    message: str
    category: str = "runtime"
    origin: str = "server"
    retryable: bool = False
    details: Dict[str, Any] = field(default_factory=dict)
    hint: Optional[str] = None

    def __str__(self) -> str:
        return self.message

    def to_error_dict(self, *, incident_id: str) -> Dict[str, Any]:
        return {
            "incident_id": incident_id,
            "type": self.__class__.__name__,
            "code": self.code,
            "message": self.message,
            "category": self.category,
            "origin": self.origin,
            "retryable": bool(self.retryable),
            "details": self.details or {},
            "hint": self.hint,
        }


def _is_retryable_exception(exc: BaseException) -> bool:
    # Conservative default. Add cases here if you want more nuance.
    retryables = (TimeoutError, ConnectionError)
    return isinstance(exc, retryables)


def _best_effort_details(exc: BaseException) -> Dict[str, Any]:
    # Keep details JSON-ish and bounded.
    try:
        return {
            "exception_type": exc.__class__.__name__,
            "exception_str": str(exc),
        }
    except Exception:
        return {"exception_type": exc.__class__.__name__}


def _single_line(s: str) -> str:
    # Ensure messages are stable and don't introduce embedded newlines into logs/UI.
    s = s.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(s.split())


def _parse_github_rate_limit_reset(message: str) -> Optional[int]:
    # Accepts messages like:
    #   "GitHub rate limit exceeded; retry after 1766682101 (resets after 1766682101)"
    m = re.search(r"resets\s+after\s+(\d{9,12})", message)
    if not m:
        m = re.search(r"retry\s+after\s+(\d{9,12})", message)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _structured_tool_error(
    exc: BaseException,
    *,
    context: Optional[str] = None,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Convert any exception into a structured payload.

    Contract:
      - returns {"error": {...}, "user_message": "..."} so callers can safely do
        payload.get("error", {}).
    """
    incident_id = str(uuid.uuid4())

    if isinstance(exc, AdaptivToolError):
        err = exc.to_error_dict(incident_id=incident_id)
        user_message = _format_user_message(err, context=context, path=path)
        return {"error": err, "user_message": user_message}

    # GitHub rate limit -> upstream, retryable, actionable (NOT a generic runtime error)
    if isinstance(exc, GitHubRateLimitError):
        msg = _single_line(str(exc) or "GitHub rate limit exceeded.")
        reset_epoch = _parse_github_rate_limit_reset(msg)
        retry_after_seconds: Optional[int] = None
        if reset_epoch is not None:
            retry_after_seconds = max(0, int(reset_epoch - time.time()))

        details = _best_effort_details(exc)
        if context:
            details["context"] = context
        if path:
            details["path"] = path
        if reset_epoch is not None:
            details["rate_limit_reset_epoch"] = reset_epoch
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds

        err = {
            "incident_id": incident_id,
            "type": exc.__class__.__name__,
            "code": "github_rate_limited",
            "message": msg,
            "category": "upstream",
            "origin": "github",
            "retryable": True,
            "details": details,
            "hint": "Wait for the reset time, reduce request frequency, or use a higher-limit GitHub credential.",
        }
        user_message = _format_user_message(err, context=context, path=path)
        return {"error": err, "user_message": user_message}

    # Generic exception -> normalized error
    err: Dict[str, Any] = {
        "incident_id": incident_id,
        "type": exc.__class__.__name__,
        "code": "unhandled_exception",
        "message": _single_line(str(exc) or exc.__class__.__name__),
        "category": "runtime",
        "origin": "exception",
        "retryable": _is_retryable_exception(exc),
        "details": _best_effort_details(exc),
        "hint": None,
    }

    # Attach optional context/path for machine readability
    if context:
        err["details"]["context"] = context
    if path:
        err["details"]["path"] = path

    user_message = _format_user_message(err, context=context, path=path)
    return {"error": err, "user_message": user_message}


def _format_user_message(err: Dict[str, Any], *, context: Optional[str], path: Optional[str]) -> str:
    # High-signal user message, still deterministic.
    parts = []

    if context:
        parts.append(f"Tool: {context}")

    msg = err.get("message") or "Unknown error."
    parts.append(f"Error: {msg}")

    if path:
        parts.append(f"Path: {path}")

    code = err.get("code")
    if code:
        parts.append(f"Code: {code}")

    category = err.get("category")
    if category:
        parts.append(f"Category: {category}")

    origin = err.get("origin")
    if origin:
        parts.append(f"Origin: {origin}")

    incident_id = err.get("incident_id")
    if incident_id:
        parts.append(f"Incident: {incident_id}")

    hint = err.get("hint")
    if hint:
        parts.append(f"Hint: {hint}")

    return " | ".join(parts)


def _exception_trace(exc: BaseException) -> str:
    """
    Optional helper: stringify a traceback when you explicitly want it.
    Do NOT auto-attach this to user-facing payloads by default.
    """
    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return f"{exc.__class__.__name__}: {exc}"
