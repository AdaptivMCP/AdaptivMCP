"""Write authorization gate and enforcement helpers.

MCP server framework: tool registry, schemas, context, and write gating.
"""

from __future__ import annotations

from typing import Literal, Optional

from github_mcp.exceptions import WriteNotAuthorizedError


def _server():
    from github_mcp import server as _server_mod

    return _server_mod


def _normalize_branch_ref(ref: Optional[str]) -> Optional[str]:
    """Normalize a ref/branch string to a bare branch name when possible.

    This understands common patterns like ``refs/heads/<name>`` but otherwise
    returns the input unchanged so commit SHAs and tags pass through.
    """

    if ref is None:
        return None
    # Strip the common refs/heads/ prefix when present.
    if ref.startswith("refs/heads/"):
        return ref[len("refs/heads/") :]
    return ref


def _ensure_write_allowed(
    context: str,
    *,
    target_ref: Optional[str] = None,
    intent: Literal["write", "push", "web", "pr", "non_harm"] = "write",
) -> None:
    """Enforce the write gate according to the auto-approve policy.

    Policy summary:
    * Auto-approve ON: all writes flow through except push-style actions
      (terminal pushes or commit helpers that mimic a push).
    * Auto-approve OFF: block any write-like terminal/action call; allow
      non-harmful metadata edits (comments, tagging, etc.).
    * Web access is always write-gated at the connector layer (handled via
      consequential metadata rather than this helper).
    * PR flows are never write-gated.
    """

    # Non-harmful changes and PR metadata edits are always allowed.
    if intent in {"pr", "non_harm"}:
        return None

    # Push-like actions are the most restrictive: they require manual approval
    # when auto-approve is enabled and fall back to the general gate otherwise.
    if intent == "push" and _server().AUTO_APPROVE_ENABLED:
        raise WriteNotAuthorizedError(
            "Push-like actions are blocked while auto-approve is enabled; "
            "disable auto-approve to allow an explicit approval first."
        )

    if not _server().WRITE_ALLOWED:
        raise WriteNotAuthorizedError(
            "Write-tagged tools are currently disabled; call authorize_write_actions "
            "to enable them for this session."
        )

    normalized = _normalize_branch_ref(target_ref)

    if intent == "push" and normalized == _server().CONTROLLER_DEFAULT_BRANCH:
        raise WriteNotAuthorizedError(
            f"Push-like actions to the controller default branch ({_server().CONTROLLER_DEFAULT_BRANCH}) "
            f"are not authorized in this session (context: {context})."
        )

    return None
