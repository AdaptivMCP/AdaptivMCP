"""
Write gate (server-side) for remote mutations.

Policy:
- The ONLY gate is github_mcp.server.WRITE_ALLOWED.
- No UI prompts / approvals are implemented here.
- When blocked, raise a structured error that is both machine-readable and user-readable.
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


def _ensure_write_allowed(
    action: str,
    *,
    write_kind: str = "soft_write",
    approved: Optional[bool] = None,
    target_ref: Optional[str] = None,
    **_ignored: Any,
) -> None:
    """
    Enforce server-side write allowance.

    Args:
        action: Human-readable description of the attempted mutation.
        write_kind: "soft_write" or "hard_write" (kept for compatibility).
        approved: accepted for backward compatibility; ignored.
        target_ref: optional branch/ref involved in the mutation.

    Raises:
        AdaptivToolError: when WRITE_ALLOWED is falsey.
    """
    if _get_write_allowed():
        return

    raise AdaptivToolError(
        code="write_not_allowed",
        message="Write operation blocked: server WRITE_ALLOWED is disabled.",
        category="permission",
        origin="write_gate",
        retryable=False,
        details={
            "action": action,
            "write_kind": write_kind,
            "target_ref": target_ref,
            "write_allowed": False,
        },
        hint=(
            "Enable writes by calling authorize_write_actions({approved:true}) "
            "or setting WRITE_ALLOWED=true in the server process."
        ),
    )