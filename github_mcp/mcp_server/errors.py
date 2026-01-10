"""
Structured error model for Adaptiv MCP.

Requirements:
- Machine readable: stable fields for programmatic handling.
- User readable: clear, detailed messages.
- No custom transformation layer is applied here (per project policy).
"""

from __future__ import annotations

import re
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

from github_mcp.config import GITHUB_TOKEN_ENV_VARS
from github_mcp.exceptions import GitHubAuthError, GitHubRateLimitError, UsageError


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


def _is_critical_error(category: Optional[str], retryable: bool) -> bool:
    if category in {
        "validation",
        "configuration",
        "permission",
        "not_found",
        "conflict",
    }:
        return False
    if category in {"timeout", "upstream"}:
        return not retryable
    if category == "runtime":
        return True
    return True


def _best_effort_details(exc: BaseException) -> Dict[str, Any]:
    # Keep details JSON-ish and bounded.
    try:
        return {
            "exception_type": exc.__class__.__name__,
            "exception_str": str(exc),
        }
    except Exception:
        return {"exception_type": exc.__class__.__name__}


def _extract_raw_payloads(exc: BaseException) -> Dict[str, Any]:
    raw: Dict[str, Any] = {}
    response_payload = getattr(exc, "response_payload", None)
    if response_payload is None:
        response_payload = getattr(exc, "raw_response", None)
    if response_payload is not None:
        raw["raw_response"] = response_payload

    raw_error = getattr(exc, "raw_error", None)
    if raw_error is not None:
        raw["raw_error"] = raw_error

    return raw


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
    request: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Convert any exception into a structured payload.

    Contract:
      - returns {"error": {...}} so callers can safely do payload.get("error", {}).
      - optional {"debug": {...}} includes raw upstream payloads when available.
    """
    incident_id = str(uuid.uuid4())

    adaptiv_exc = _unwrap_adaptiv_error(exc)
    if adaptiv_exc is not None:
        err = adaptiv_exc.to_error_dict(incident_id=incident_id)
        err.setdefault(
            "critical",
            _is_critical_error(err.get("category"), bool(err.get("retryable"))),
        )
        payload = {"error": err}
        if request is not None:
            payload["request"] = request
        debug = _extract_raw_payloads(exc)
        if debug:
            payload["debug"] = debug
        return payload

    if isinstance(exc, GitHubAuthError):
        msg = _single_line(str(exc) or "GitHub authentication failed.")
        err = {
            "incident_id": incident_id,
            "type": exc.__class__.__name__,
            "code": "github_auth_failed",
            "message": msg,
            "category": "permission",
            "origin": "github",
            "retryable": False,
            "critical": _is_critical_error("permission", False),
            "details": {
                "env_vars": list(GITHUB_TOKEN_ENV_VARS),
                **({"context": context} if context else {}),
                **({"path": path} if path else {}),
            },
            # IMPORTANT: avoid masking the true issue by claiming this is always an env-var problem.
            "hint": (
                "GitHub repository access is not available to this process (or git cannot use the configured credentials). "
                "If you rely on platform-injected secrets (e.g., Render runtime env), confirm they are attached to the service "
                "and visible to the git subprocess. If you use env vars, set one of the supported GitHub token variables."
            ),
        }
        payload = {"error": err}
        if request is not None:
            payload["request"] = request
        debug = _extract_raw_payloads(exc)
        if debug:
            payload["debug"] = debug
        return payload

    if isinstance(exc, UsageError):
        msg = _single_line(str(exc) or "Invalid usage.")
        details = _best_effort_details(exc)
        details.update({"context": context} if context else {})
        details.update({"path": path} if path else {})

        category = "validation"
        origin = "tool"
        hint = None

        err = {
            "incident_id": incident_id,
            "type": exc.__class__.__name__,
            "code": "usage_error",
            "message": msg,
            "category": category,
            "origin": origin,
            "retryable": False,
            "critical": _is_critical_error(category, False),
            "details": details,
            "hint": hint,
        }
        payload = {"error": err}
        if request is not None:
            payload["request"] = request
        debug = _extract_raw_payloads(exc)
        if debug:
            payload["debug"] = debug
        return payload

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
            "critical": _is_critical_error("upstream", True),
            "details": details,
            "hint": "Wait for the reset time, reduce request frequency, or use a higher-limit GitHub credential.",
        }
        payload = {"error": err}
        if request is not None:
            payload["request"] = request
        debug = _extract_raw_payloads(exc)
        if debug:
            payload["debug"] = debug
        return payload

    # Generic exception -> normalized error
    err: Dict[str, Any] = {
        "incident_id": incident_id,
        "type": exc.__class__.__name__,
        "code": "unhandled_exception",
        "message": _single_line(str(exc) or exc.__class__.__name__),
        "category": "runtime",
        "origin": "exception",
        "retryable": _is_retryable_exception(exc),
        "critical": _is_critical_error("runtime", _is_retryable_exception(exc)),
        "details": _best_effort_details(exc),
        "hint": None,
    }

    # Attach optional context/path for machine readability
    if context:
        err["details"]["context"] = context
    if path:
        err["details"]["path"] = path

    payload = {"error": err}
    if request is not None:
        payload["request"] = request
    debug = _extract_raw_payloads(exc)
    if debug:
        payload["debug"] = debug
    return payload


def _unwrap_adaptiv_error(exc: BaseException) -> Optional[AdaptivToolError]:
    if isinstance(exc, AdaptivToolError):
        return exc
    seen: Set[int] = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        cause = getattr(current, "__cause__", None)
        if isinstance(cause, AdaptivToolError):
            return cause
        context = getattr(current, "__context__", None)
        if isinstance(context, AdaptivToolError):
            return context
        current = cause or context
    return None


def _exception_trace(exc: BaseException) -> str:
    """
    Optional helper: stringify a traceback when you explicitly want it.
    Do NOT auto-attach this to user-facing payloads by default.
    """
    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return f"{exc.__class__.__name__}: {exc}"
