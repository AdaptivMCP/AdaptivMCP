from __future__ import annotations

from typing import Optional

def _server():
    from github_mcp import server as _server_mod

    return _server_mod


def _ensure_write_allowed(context: str, *, target_ref: Optional[str] = None) -> None:
    """No-op write gate (server-side blocks removed).

    Write gating previously enforced server-side approval before running
    write-tagged tools. The controller now always permits these calls. The
    signature remains for compatibility with callers that still invoke it.

    `target_ref` is accepted for backwards compatibility with older call sites,
    but it is intentionally ignored.
    """

    return None
