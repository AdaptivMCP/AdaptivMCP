"""
Write gate (server-side) for mutations.

Policy:
- Reads are always allowed.
- When WRITE_ALLOWED is true, soft AND hard writes are allowed.
- When WRITE_ALLOWED is false, writes are blocked (no approval flow).
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
    """Return True when a write is blocked by policy."""
    if write_kind == "read_only":
        return False
    return not bool(write_allowed)


def _ensure_write_allowed(
    action: str,
    *,
    write_kind: str = "soft_write",
    approved: Optional[bool] = None,
    target_ref: Optional[str] = None,
    **_ignored: Any,
) -> None:
    """
    Enforce server-side write allowance requirements.

    Args:
        action: Human-readable description of the attempted mutation.
        write_kind: "read_only", "soft_write", or "hard_write".
        approved: Deprecated; retained for backward compatibility (ignored).
        target_ref: optional branch/ref involved in the mutation.

    Raises:
        AdaptivToolError: when writes are disabled.
    """
    write_allowed = _get_write_allowed()
    if not _requires_approval(write_allowed, write_kind):
        return

    raise AdaptivToolError(
        code="write_not_allowed",
        message="Write operations are disabled (WRITE_ALLOWED=false).",
        category="permission",
        origin="write_gate",
        retryable=False,
        details={
            "action": action,
            "write_kind": write_kind,
            "target_ref": target_ref,
            "write_allowed": write_allowed,
            "approval_required": False,
        },
        hint="Set WRITE_ALLOWED=true to enable writes.",
    )
