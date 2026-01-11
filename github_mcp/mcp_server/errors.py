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
from typing import Any, Dict, Optional

from github_mcp.config import GITHUB_TOKEN_ENV_VARS
from github_mcp.exceptions import GitHubAuthError, GitHubRateLimitError, UsageError
from github_mcp.mcp_server.context import get_request_id


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


def _structured_exception_overrides(
    exc: BaseException,
    *,
    incident_id: str,
    request_id: Optional[str],
    context: Optional[str],
    path: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Best-effort support for exceptions that carry structured fields.

    This avoids a bespoke exception type while still allowing callers to provide
    stable error metadata. Any exception can opt-in by setting attributes:
      - code (required)
      - message (optional; falls back to str(exc))
      - category, origin, retryable, details (dict), hint
    """

    code = getattr(exc, "code", None)
    if not code:
        return None

    msg = getattr(exc, "message", None)
    if not msg:
        msg = str(exc) or exc.__class__.__name__

    category = getattr(exc, "category", None) or "runtime"
    origin = getattr(exc, "origin", None) or "exception"

    retryable_attr = getattr(exc, "retryable", None)
    retryable = bool(retryable_attr) if retryable_attr is not None else _is_retryable_exception(exc)

    details: Dict[str, Any] = _best_effort_details(exc)
    details_attr = getattr(exc, "details", None)
    if isinstance(details_attr, dict):
        details.update(details_attr)
    if context:
        details.setdefault("context", context)
    if path:
        details.setdefault("path", path)

    hint = getattr(exc, "hint", None)

    return {
        "incident_id": incident_id,
        "request_id": request_id,
        "type": exc.__class__.__name__,
        "code": str(code),
        "message": _single_line(str(msg)),
        "category": str(category),
        "origin": str(origin),
        "retryable": retryable,
        "critical": _is_critical_error(str(category), retryable),
        "details": details,
        "hint": str(hint) if hint is not None else None,
    }


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
) -> Dict[str, Any]:
    """
    Convert any exception into a structured payload.

    Contract:
      - returns {"error": {...}} so callers can safely do payload.get("error", {}).
    """
    incident_id = str(uuid.uuid4())
    request_id = get_request_id()

    overridden = _structured_exception_overrides(
        exc,
        incident_id=incident_id,
        request_id=request_id,
        context=context,
        path=path,
    )
    if overridden is not None:
        payload = {
            "error": overridden,
            "tool_descriptor": tool_descriptor,
            "tool_descriptor_text": tool_descriptor_text,
            "tool_surface": tool_surface,
            "routing_hint": routing_hint,
            "request": request,
        }
        payload.update(_extract_raw_payloads(exc))
        return payload

    if isinstance(exc, GitHubAuthError):
        msg = _single_line(str(exc) or "GitHub authentication failed.")
        err = {
            "incident_id": incident_id,
            "request_id": request_id,
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
        payload = {
            "error": err,
            "tool_descriptor": tool_descriptor,
            "tool_descriptor_text": tool_descriptor_text,
            "tool_surface": tool_surface,
            "routing_hint": routing_hint,
            "request": request,
        }
        payload.update(_extract_raw_payloads(exc))
        return payload

    if isinstance(exc, UsageError):
        msg = _single_line(str(exc) or "Invalid usage.")
        details: Dict[str, Any] = _best_effort_details(exc)
        details.update({"context": context} if context else {})
        details.update({"path": path} if path else {})
        details_attr = getattr(exc, "details", None)
        if isinstance(details_attr, dict):
            details.update(details_attr)

        category = getattr(exc, "category", None) or "validation"
        origin = getattr(exc, "origin", None) or "tool"
        hint = getattr(exc, "hint", None)
        code = getattr(exc, "code", None) or "usage_error"
        retryable = bool(getattr(exc, "retryable", False))

        err = {
            "incident_id": incident_id,
            "request_id": request_id,
            "type": exc.__class__.__name__,
            "code": str(code),
            "message": msg,
            "category": str(category),
            "origin": str(origin),
            "retryable": retryable,
            "critical": _is_critical_error(str(category), retryable),
            "details": details,
            "hint": str(hint) if hint is not None else None,
        }
        payload = {
            "error": err,
            "tool_descriptor": tool_descriptor,
            "tool_descriptor_text": tool_descriptor_text,
            "tool_surface": tool_surface,
            "routing_hint": routing_hint,
            "request": request,
        }
        payload.update(_extract_raw_payloads(exc))
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
            "request_id": request_id,
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
        payload = {
            "error": err,
            "tool_descriptor": tool_descriptor,
            "tool_descriptor_text": tool_descriptor_text,
            "tool_surface": tool_surface,
            "routing_hint": routing_hint,
            "request": request,
        }
        payload.update(_extract_raw_payloads(exc))
        return payload

    # Generic exception -> normalized error
    err: Dict[str, Any] = {
        "incident_id": incident_id,
        "request_id": request_id,
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

    payload = {
        "error": err,
        "tool_descriptor": tool_descriptor,
        "tool_descriptor_text": tool_descriptor_text,
        "tool_surface": tool_surface,
        "routing_hint": routing_hint,
        "request": request,
    }
    payload.update(_extract_raw_payloads(exc))
    return payload


def _exception_trace(exc: BaseException) -> str:
    """
    Optional helper: stringify a traceback when you explicitly want it.
    Do NOT auto-attach this to user-facing payloads by default.
    """
    try:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        return f"{exc.__class__.__name__}: {exc}"
