from __future__ import annotations

from typing import Optional

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


def _ensure_write_allowed(context: str, *, target_ref: Optional[str] = None) -> None:
    """Enforce write gating with special handling for the default branch.

    * Unscoped operations (no ``target_ref``) still honor the global
      ``_server().WRITE_ALLOWED`` flag so controllers can fully disable dangerous tools.
    * Writes that explicitly target the controller default branch remain gated
      on ``_server().WRITE_ALLOWED`` so commits to ``main`` (or whatever
      _server().CONTROLLER_DEFAULT_BRANCH is set to) always require an approval call.
    * Writes to non-default branches are allowed even when ``_server().WRITE_ALLOWED`` is
      false so assistants can iterate safely on feature branches.
    """

    # When we do not know which ref a tool will touch, fall back to the global
    # kill switch so destructive tools remain opt-in.
    if target_ref is None:
        if not _server().WRITE_ALLOWED:
            raise WriteNotAuthorizedError(
                "Write-tagged tools are currently disabled for unscoped operations; "
                "call authorize_write_actions to enable them for this session."
            )
        return None

    normalized = _normalize_branch_ref(target_ref)

    # Writes aimed at the controller default branch still require explicit
    # authorization via authorize_write_actions.
    if normalized == _server().CONTROLLER_DEFAULT_BRANCH and not _server().WRITE_ALLOWED:
        raise WriteNotAuthorizedError(
            f"Writes to the controller default branch ({_server().CONTROLLER_DEFAULT_BRANCH}) "
            f"are not yet authorized (context: {context}); call "
            "authorize_write_actions before committing directly to the default branch."
        )

    # Writes to any non-default branch are always allowed from the connector's
    # perspective. Repository protection rules and GitHub permissions still
    # apply server-side.
    return None
