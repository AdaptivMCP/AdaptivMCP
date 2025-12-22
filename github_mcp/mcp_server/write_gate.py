from __future__ import annotations

from typing import Optional

from github_mcp.exceptions import WriteNotAuthorizedError


def _server():
    from github_mcp import server as _server_mod

    return _server_mod


def _ensure_write_allowed(context: str, *, target_ref: Optional[str] = None) -> None:
    """Enforce global write gating.

    This server uses a single, explicit toggle (`_server().WRITE_ALLOWED`) to
    control *all* write-tagged tools.

    - When WRITE_ALLOWED is False: every write-tagged tool call is rejected.
    - When WRITE_ALLOWED is True: write-tagged tools may proceed.

    `target_ref` is accepted for backwards compatibility with older call sites,
    but it is intentionally ignored.
    """

    if not _server().WRITE_ALLOWED:
        raise WriteNotAuthorizedError(
            "Write-tagged tools are currently disabled; call authorize_write_actions "
            f"to enable them for this session (context: {context})."
        )

    return None
