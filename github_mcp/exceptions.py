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


class ToolArgNormalizationError(ValueError):
    """Raised when tool arguments cannot be safely normalized."""

    pass


class ToolPreflightValidationError(ValueError):
    """Raised when tool payloads fail server-side preflight validation."""

    pass


__all__ = [
    "GitHubAPIError",
    "GitHubAuthError",
    "GitHubRateLimitError",
    "WriteNotAuthorizedError",
    "ToolArgNormalizationError",
    "ToolPreflightValidationError",
]
