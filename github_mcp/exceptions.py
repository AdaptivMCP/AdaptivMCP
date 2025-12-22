"""Custom exception types used across the GitHub MCP server."""

from __future__ import annotations


class GitHubAuthError(Exception):
    pass


class GitHubAPIError(Exception):
    pass


class GitHubRateLimitError(GitHubAPIError):
    """Raised when GitHub responds with a rate limit error."""

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


__all__ = [
    "GitHubAPIError",
    "GitHubAuthError",
    "GitHubRateLimitError",
    "WriteNotAuthorizedError",
    "WriteApprovalRequiredError",
    "ToolPreflightValidationError",
    "UsageError",
]
