"""Top-level package exports for github_mcp.

This module centralises the public API surface that tests (and users) import
from `github_mcp` rather than the underlying modules. Keeping this list
explicit helps avoid accidental breakage when module internals change."""
from __future__ import annotations

from .http_clients import (
    GitHubAPIClient,
    GitHubIntegrationTokenClient,
    GitHubUserTokenClient,
    GitHubAppInstallationTokenClient,
    GitHubTokenType,
)
from .tools_workspace import WorkspaceRunContext
from . import metrics as _metrics
from . import exceptions as _exceptions

# --- Metrics -----------------------------------------------------------------
# Historically the logger type has been referred to with both `Github` and
# `GitHub` spellings. To keep the package ergonomic (and to support existing
# tests) we export both names as aliases to the same underlying class.
if hasattr(_metrics, "GithubActionUsageLogger"):
    GithubActionUsageLogger = _metrics.GithubActionUsageLogger  # type: ignore[attr-defined]
    GitHubActionUsageLogger = GithubActionUsageLogger
elif hasattr(_metrics, "GitHubActionUsageLogger"):
    GitHubActionUsageLogger = _metrics.GitHubActionUsageLogger  # type: ignore[attr-defined]
    GithubActionUsageLogger = GitHubActionUsageLogger
else:  # pragma: no cover - defensive guard if the internal name ever changes.
    raise ImportError("metrics module does not define an action usage logger type")

# --- Exceptions --------------------------------------------------------------
GitHubAPIError = _exceptions.GitHubAPIError
GitHubAuthenticationError = _exceptions.GitHubAuthenticationError

# Similar aliasing strategy for workflow errors where the name may have been
# spelt with either `Github` or `GitHub` historically.
if hasattr(_exceptions, "GithubActionWorkflowError"):
    GithubActionWorkflowError = _exceptions.GithubActionWorkflowError  # type: ignore[attr-defined]
    GitHubActionWorkflowError = GithubActionWorkflowError
elif hasattr(_exceptions, "GitHubActionWorkflowError"):
    GitHubActionWorkflowError = _exceptions.GitHubActionWorkflowError  # type: ignore[attr-defined]
    GithubActionWorkflowError = GitHubActionWorkflowError
else:  # pragma: no cover
    raise ImportError("exceptions module does not define an action workflow error type")

__all__ = [
    "GitHubAPIClient",
    "GitHubIntegrationTokenClient",
    "GitHubUserTokenClient",
    "GitHubAppInstallationTokenClient",
    "GitHubTokenType",
    "GitHubActionUsageLogger",
    "GithubActionUsageLogger",
    "GitHubAPIError",
    "GitHubAuthenticationError",
    "GitHubActionWorkflowError",
    "GithubActionWorkflowError",
    "WorkspaceRunContext",
]
