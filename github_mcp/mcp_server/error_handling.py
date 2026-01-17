"""Structured error helpers used across tool and HTTP surfaces.

This module intentionally centralizes error normalization so:
- Tool wrappers can return a stable envelope without raising.
- HTTP routes can map errors to status codes reliably.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from github_mcp.exceptions import (
    GitHubAuthError,
    GitHubRateLimitError,
    RenderAuthError,
    WriteApprovalRequiredError,
    WriteNotAuthorizedError,
)


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
    message = str(exc) or exc.__class__.__name__

    # Best-effort categorization for consistent HTTP status mapping.
    category = "internal"
    code: Optional[str] = None
    details: Dict[str, Any] = {}

    if isinstance(exc, (GitHubAuthError, RenderAuthError)):
        category = "auth"
    elif isinstance(exc, GitHubRateLimitError):
        category = "rate_limited"
        code = "github_rate_limited"
    elif isinstance(exc, (WriteApprovalRequiredError, WriteNotAuthorizedError)):
        category = "permission"
        if isinstance(exc, WriteApprovalRequiredError):
            category = "write_approval_required"
            code = "WRITE_APPROVAL_REQUIRED"
    elif isinstance(exc, (ValueError, TypeError)):
        category = "validation"

    error_detail: Dict[str, Any] = {
        "message": message,
        "category": category,
    }
    if code:
        error_detail["code"] = code
    if details:
        error_detail["details"] = details

    # Keep trace/debug nested under error_detail for stable downstream consumers
    # (tests and HTTP routes).
    if trace is not None:
        error_detail["trace"] = trace
    if args is not None:
        error_detail["debug"] = {"args": args}

    payload: Dict[str, Any] = {
        "status": "error",
        "error": message,
        "error_detail": error_detail,
    }
    if context:
        payload["context"] = context
    if path:
        payload["path"] = path
    if request is not None:
        payload["request"] = request
    if tool_surface is not None:
        payload["tool_surface"] = tool_surface
    if routing_hint is not None:
        payload["routing_hint"] = routing_hint
    if tool_descriptor is not None:
        payload["tool_descriptor"] = tool_descriptor
    if tool_descriptor_text is not None:
        payload["tool_descriptor_text"] = tool_descriptor_text

    return payload
