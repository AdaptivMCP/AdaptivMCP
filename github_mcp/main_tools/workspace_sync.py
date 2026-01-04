from __future__ import annotations

from typing import Any, Dict, Optional

import sys

from github_mcp.config import BASE_LOGGER
from github_mcp.github_content import _perform_github_commit as _default_commit
from github_mcp.workspace_tools.clone import (
    ensure_workspace_clone as _default_ensure_workspace_clone,
)

LOGGER = BASE_LOGGER.getChild("workspace_sync")


async def _perform_github_commit_and_refresh_workspace(
    *,
    full_name: str,
    path: str,
    message: str,
    branch: str,
    body_bytes: bytes,
    sha: Optional[str],
) -> Dict[str, Any]:
    """Perform a Contents API commit and then refresh the workspace clone.

    This keeps the long-lived workspace clone in sync with the branch when
    writes happen directly via the GitHub Contents API. Workspace refresh
    failures are logged but never fail the commit itself.
    """

    main_mod = sys.modules.get("main") or sys.modules.get("__main__")
    commit_fn = (
        getattr(main_mod, "_perform_github_commit", _default_commit)
        if main_mod
        else _default_commit
    )
    commit_result = await commit_fn(
        full_name=full_name,
        path=path,
        message=message,
        body_bytes=body_bytes,
        branch=branch,
        sha=sha,
    )

    try:
        ensure_fn = (
            getattr(main_mod, "ensure_workspace_clone", _default_ensure_workspace_clone)
            if main_mod
            else _default_ensure_workspace_clone
        )
        refresh = await ensure_fn(
            full_name=full_name,
            ref=branch,
            reset=True,
        )
        if isinstance(refresh, dict) and refresh.get("error"):
            LOGGER.debug(
                "Workspace refresh returned an error after commit",
                extra={
                    "full_name": full_name,
                    "branch": branch,
                    "error": refresh.get("error"),
                },
            )
    except Exception as exc:  # pragma: no cover - defensive logging only
        LOGGER.debug(
            "Failed to refresh workspace after commit",
            extra={
                "full_name": full_name,
                "branch": branch,
                "error": str(exc),
            },
        )

    return commit_result
