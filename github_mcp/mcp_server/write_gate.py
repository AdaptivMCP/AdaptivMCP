from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from github_mcp.exceptions import WriteApprovalRequiredError

WriteKind = Literal["read", "soft_write", "hard_write"]


@dataclass(frozen=True)
class WriteGateDecision:
    write_kind: WriteKind
    write_allowed: bool
    approved: bool
    target_ref: Optional[str] = None

    @property
    def approval_required(self) -> bool:
        return self.write_kind == "hard_write" or not self.write_allowed

    @property
    def allowed(self) -> bool:
        return self.approved or not self.approval_required

def _server():
    from github_mcp import server as _server_mod

    return _server_mod


def _build_decision(
    *, write_kind: WriteKind, target_ref: Optional[str] = None, approved: Optional[bool] = None
) -> WriteGateDecision:
    """Compute gate state.

    Semantics:
    - READs are not gated here (callers should not invoke this for read-only tools).
    - HARD_WRITE always requires explicit approval.
    - SOFT_WRITE is allowed when either:
        a) WRITE_ALLOWED is true (auto-approve on), or
        b) the caller supplies approved=True (manual approval path).

    This ensures soft writes can still proceed when auto-approve is off, but only
    with explicit approval.
    """

    server_mod = _server()
    write_allowed = bool(getattr(server_mod, "WRITE_ALLOWED", False))

    approved_flag = bool(approved) if approved is not None else False

    if write_kind == "hard_write":
        return WriteGateDecision(
            write_kind=write_kind,
            write_allowed=write_allowed,
            approved=approved_flag,
            target_ref=target_ref,
        )

    # soft_write
    return WriteGateDecision(
        write_kind=write_kind,
        write_allowed=write_allowed,
        approved=(write_allowed or approved_flag),
        target_ref=target_ref,
    )


def _ensure_write_allowed(
    context: str,
    *,
    target_ref: Optional[str] = None,
    write_kind: WriteKind = "hard_write",
    approved: Optional[bool] = None,
) -> None:
    """Gate write attempts and surface user-friendly approval errors."""

    decision = _build_decision(write_kind=write_kind, target_ref=target_ref, approved=approved)

    if decision.allowed:
        return None

    gate_info = {
        "write_kind": decision.write_kind,
        "write_allowed": decision.write_allowed,
        "target_ref": decision.target_ref,
        "approval_required": decision.approval_required,
        "approved": decision.approved,
    }

    reason = "UI approval is required" if decision.write_kind == "hard_write" else "Write actions are currently disabled"
    msg = f"{context}: {reason}."

    exc = WriteApprovalRequiredError(msg)
    setattr(exc, "write_gate", gate_info)
    raise exc
