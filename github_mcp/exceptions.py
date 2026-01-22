"""Custom exception types used across the GitHub MCP server."""

from __future__ import annotations

from typing import Any


class APIError(Exception):
    """Base error type for upstream/provider API failures."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_payload = response_payload


class GitHubAuthError(Exception):
    pass


class GitHubAPIError(APIError):
    pass


class GitHubRateLimitError(GitHubAPIError):
    """Raised when GitHub responds with a rate limit error."""

    pass


class RenderAuthError(Exception):
    """Raised when Render API authentication is missing or invalid."""


class RenderAPIError(APIError):
    pass


class WriteNotAuthorizedError(Exception):
    pass


class WriteApprovalRequiredError(WriteNotAuthorizedError):
    code = "WRITE_APPROVAL_REQUIRED"


class ToolPreflightValidationError(Exception):
    """Raised when server-side tool argument preflight fails.

    This error is intentionally lightweight so callers see a clear, single-line
    message that points at the offending tool and field.
    """

    def __init__(self, tool: str, message: str) -> None:
        super().__init__(f"Preflight validation failed for tool {tool!r}: {message}")
        self.tool = tool


class UsageError(Exception):
    """Raised when a tool cannot proceed due to user misconfiguration or bad inputs.

    This is intended to surface a clear, single-line message to the caller.
    """

    pass


class ToolOperationError(Exception):
    """Raised when a tool fails during execution (not a user input validation error).

    This error type supports structured fields consumed by `_structured_tool_error`
    for consistent categorization and developer-facing diagnostics.
    """

    def __init__(
        self,
        message: str,
        *,
        category: str = "internal",
        code: str | None = None,
        details: dict[str, Any] | None = None,
        hint: str | None = None,
        origin: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.code = code
        self.details = details or {}
        self.hint = hint
        self.origin = origin
        self.retryable = bool(retryable)


__all__ = [
    "APIError",
    "GitHubAPIError",
    "GitHubAuthError",
    "GitHubRateLimitError",
    "RenderAPIError",
    "RenderAuthError",
    "WriteNotAuthorizedError",
    "WriteApprovalRequiredError",
    "ToolPreflightValidationError",
    "UsageError",
    "ToolOperationError",
]
