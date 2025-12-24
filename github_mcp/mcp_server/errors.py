"""Utilities for producing consistent tool-failure payloads.

This controller is the source of truth for how tool failures are reported.
The payload shape should remain stable so clients can rely on it.

Policy:
- Do not attribute failures to any external platform/provider.
- Keep diagnostics optional and controlled by GITHUB_MCP_DIAGNOSTICS.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

import jsonschema

from github_mcp.config import BASE_LOGGER
from github_mcp.exceptions import WriteApprovalRequiredError, WriteNotAuthorizedError
from github_mcp.mcp_server.context import GITHUB_MCP_DIAGNOSTICS, WRITE_ALLOWED


@dataclass(frozen=True)
class ToolInputValidationError(ValueError):
    """Raised when tool inputs fail controller-side validation."""

    tool_name: str
    message: str
    field: str | None = None

    def __str__(self) -> str:  # pragma: no cover
        if self.field:
            return f"{self.tool_name}: {self.message} (field={self.field})"
        return f"{self.tool_name}: {self.message}"


def _summarize_exception(exc: BaseException) -> str:
    """Create a short human-readable message."""

    if isinstance(exc, jsonschema.ValidationError):
        path = list(exc.path)
        base_message = exc.message or exc.__class__.__name__
        if path:
            path_display = " → ".join(str(p) for p in path)
            return f"{base_message} (at {path_display})"
        return base_message

    return str(exc) or exc.__class__.__name__


def _classify_category(exc: BaseException, message: str) -> str:
    """Best-effort category for client UX and retry logic."""

    if isinstance(exc, WriteApprovalRequiredError):
        return "write_approval_required"
    if isinstance(exc, WriteNotAuthorizedError):
        return "write_not_authorized"

    if isinstance(exc, (jsonschema.ValidationError, ToolInputValidationError, ValueError, TypeError)):
        return "validation"

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "timeout"

    lowered = (message or "").lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"

    # Keep as a soft signal; avoids importing provider-specific exceptions here.
    if exc.__class__.__name__ in {"GitHubAPIError", "GitHubAuthError", "GitHubRateLimitError"}:
        return "github_api"

    return "unknown"


def _next_steps(*, category: str) -> list[dict[str, Any]]:
    """Return structured guidance for the assistant."""

    def mk(kind: str, **kwargs: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "kind": kind,
            "actor": "assistant",
            "user_can_invoke_tools": False,
        }
        base.update(kwargs)
        return base

    if category == "write_approval_required":
        return [
            mk(
                "approval",
                action="This operation requires approval. Enable write actions and retry.",
            )
        ]

    if category == "validation":
        return [
            mk(
                "args",
                tool="describe_tool",
                action="Validate tool parameters and retry.",
            )
        ]

    if category == "timeout":
        return [
            mk(
                "timeout",
                tool="run_command",
                action="Retry with a higher timeout or split into smaller steps.",
            )
        ]

    return [mk("controller", action="Review logs and retry with smaller steps if needed.")]


def _structured_tool_error(
    exc: BaseException, *, context: str, path: Optional[str] = None
) -> Dict[str, Any]:
    """Build a serializable payload for MCP clients."""

    message = _summarize_exception(exc)
    category = _classify_category(exc, message)

    if GITHUB_MCP_DIAGNOSTICS:
        BASE_LOGGER.exception(
            "Tool failure",
            extra={
                "tool_context": context,
                "tool_exception": exc.__class__.__name__,
                "tool_message": message,
                "tool_path": path,
                "tool_category": category,
                "tool_write_allowed": WRITE_ALLOWED,
            },
        )

    payload: Dict[str, Any] = {
        "error": {
            "error": exc.__class__.__name__,
            "message": message,
            "context": context,
            "origin": "controller",
            "category": category,
            "write_allowed": WRITE_ALLOWED,
            "actor": "assistant",
            "user_can_invoke_tools": False,
            "next_steps": _next_steps(category=category),
        }
    }

    if getattr(exc, "code", None):
        payload["error"]["code"] = getattr(exc, "code")

    if isinstance(exc, WriteApprovalRequiredError):
        payload["error"]["approval_required"] = True

    if getattr(exc, "write_gate", None):
        payload["error"]["write_gate"] = getattr(exc, "write_gate")

    if path:
        payload["error"]["path"] = path

    return payload
