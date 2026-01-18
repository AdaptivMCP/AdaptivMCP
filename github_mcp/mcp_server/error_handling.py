"""Structured error helpers used across tool and HTTP surfaces.

This module centralizes error normalization so:
- Tool wrappers can return a stable envelope without raising.
- HTTP routes can map errors to status codes reliably.

Contract notes:
- Keep top-level keys stable (status/error/error_detail).
- Add new information under error_detail.
"""

from __future__ import annotations

from typing import Any

from github_mcp.exceptions import (
    APIError,
    GitHubAuthError,
    GitHubRateLimitError,
    RenderAuthError,
    UsageError,
    WriteApprovalRequiredError,
    WriteNotAuthorizedError,
)


def _structured_tool_error(
    exc: BaseException,
    *,
    context: str | None = None,
    path: str | None = None,
    tool_descriptor: dict[str, Any] | None = None,
    tool_descriptor_text: str | None = None,
    tool_surface: str | None = None,
    routing_hint: dict[str, Any] | None = None,
    request: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = str(exc) or exc.__class__.__name__

    # Best-effort categorization for consistent HTTP status mapping.
    category = "internal"
    code: str | None = None
    details: dict[str, Any] = {}
    retryable = False
    hint: str | None = None
    origin: str | None = None

    # 1) Capture any structured attributes attached to the exception.
    # Tools may raise plain Exceptions, so treat this as opportunistic.
    val = getattr(exc, "code", None)
    if isinstance(val, str) and val.strip():
        code = val.strip()

    val = getattr(exc, "category", None)
    if isinstance(val, str) and val.strip():
        category = val.strip()

    val = getattr(exc, "hint", None)
    if isinstance(val, str) and val.strip():
        hint = val.strip()

    val = getattr(exc, "origin", None)
    if isinstance(val, str) and val.strip():
        origin = val.strip()

    val = getattr(exc, "retryable", None)
    if isinstance(val, bool):
        retryable = val
    elif val is not None:
        retryable = bool(val)

    val = getattr(exc, "details", None)
    if isinstance(val, dict) and val:
        details.update(val)

    # 2) Provider/permission categories.
    if isinstance(exc, (GitHubAuthError, RenderAuthError)):
        category = "auth"
    elif isinstance(exc, GitHubRateLimitError):
        category = "rate_limited"
        code = code or "github_rate_limited"
        retryable = True
    elif isinstance(exc, (WriteApprovalRequiredError, WriteNotAuthorizedError)):
        category = "permission"
        if isinstance(exc, WriteApprovalRequiredError):
            category = "write_approval_required"
            code = code or "WRITE_APPROVAL_REQUIRED"
    elif isinstance(exc, (ValueError, TypeError)):
        category = "validation"

    # 3) APIError carries upstream status/payload; map common statuses.
    if isinstance(exc, APIError):
        details.setdefault("upstream_status_code", exc.status_code)
        if isinstance(exc.response_payload, dict) and exc.response_payload:
            details.setdefault("upstream_payload", exc.response_payload)

        if exc.status_code == 401:
            category = "auth"
        elif exc.status_code == 403:
            category = "permission"
        elif exc.status_code == 404:
            category = "not_found"
        elif exc.status_code == 409:
            category = "conflict"
        elif exc.status_code == 429:
            category = "rate_limited"
            retryable = True
        elif isinstance(exc.status_code, int) and exc.status_code >= 500:
            category = "upstream"
            retryable = True

    # 4) UsageError is a user-facing error by default.
    if isinstance(exc, UsageError) and category == "internal":
        category = "validation"

    error_detail: dict[str, Any] = {
        "message": message,
        "category": category,
    }
    if code:
        error_detail["code"] = code
    if details:
        error_detail["details"] = details
    if retryable:
        error_detail["retryable"] = True
    if hint:
        error_detail["hint"] = hint
    if origin:
        error_detail["origin"] = origin

    # Keep trace/debug nested under error_detail for stable downstream consumers.
    if trace is not None:
        error_detail["trace"] = trace
    if args is not None:
        error_detail["debug"] = {"args": args}

    payload: dict[str, Any] = {
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
