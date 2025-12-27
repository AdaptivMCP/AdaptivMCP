"""Write gate shim for backward compatibility (no-op)."""

from __future__ import annotations

from typing import Any, Optional


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
    Legacy shim retained for compatibility (no-op).

    Args:
        action: Human-readable description of the attempted mutation.
        write_kind: "read_only", "soft_write", or "hard_write".
        approved: Deprecated; retained for backward compatibility (ignored).
        target_ref: optional branch/ref involved in the mutation.
    """
    return
