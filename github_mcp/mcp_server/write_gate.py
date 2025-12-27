"""
Write gate (server-side) for mutations.

Policy:
- Reads are always allowed.
- When WRITE_ALLOWED is true, soft AND hard writes are auto-approved.
- When WRITE_ALLOWED is false, any write requires explicit user approval.
"""

from __future__ import annotations

from typing import Any, Optional

from github_mcp.mcp_server.errors import AdaptivToolError


def _get_write_allowed() -> bool:
    try:
        import github_mcp.server as server_mod  # local import to avoid cycles
        return bool(getattr(server_mod, "WRITE_ALLOWED", False))
    except Exception:
        return False


def _requires_approval(write_allowed: bool, write_kind: str) -> bool:
    """
    Return True when an explicit approval signal is required.

    With this policy, WRITE_ALLOWED=True disables approval requirements for all writes.
    """
    if write_kind == "read_only":
        return False
    # If auto-approve is enabled, no approval is required for any write kind.
    if bool(write_allowed):
        return False
    # Otherwise, any write requires explicit approval.
    return True


def _ensure_write_allowed(
    action: str,
    *,
    write_kind: str = "soft_write",
    approved: Optional[bool] = None,
    target_ref: Optional[str] = None,
    **_ignored: Any,
) -> None:
    """
    Enforce server-side write approval requirements.

    Args:
        action: Human-readable description of the attempted mutation.
        write_kind: "read_only", "soft_write", or "hard_write".
        approved: When True, indicates the user explicitly approved the write.
        target_ref: optional branch/ref involved in the mutation.

    Raises:
        AdaptivToolError: when the write requires approval.
    """
    write_allowed = _get_write_allowed()
    if not _requires_approval(write_allowed, write_kind):
        return
    if approved:
        return

    raise AdaptivToolError(
        code="write_approval_required",
        message="Write operation requires explicit user approval.",
        category="permission",
        origin="write_gate",
        retryable=False,
        details={
            "action": action,
            "write_kind": write_kind,
            "target_ref": target_ref,
            "write_allowed": write_allowed,
            "approval_required": True,
        },
        hint=(
            "Approve the write in the client UI. To auto-approve writes, "
            "call authorize_write_actions({approved:true}) or set WRITE_ALLOWED=true."
        ),
    )