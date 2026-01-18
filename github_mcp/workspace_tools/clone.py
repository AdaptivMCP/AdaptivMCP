"""Generated repo mirror helpers (workspace clone)."""

from __future__ import annotations

import os
from typing import Any

from github_mcp.server import _structured_tool_error, mcp_tool

from ._shared import _tw


@mcp_tool(write_action=False)
async def ensure_workspace_clone(
    full_name: str,
    ref: str = "main",
    reset: bool = False,
) -> dict[str, Any]:
    """Ensure a persistent repo mirror (workspace clone) exists for a repo/ref."""

    try:
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        workspace_dir = _tw()._workspace_path(full_name, effective_ref)
        existed = os.path.isdir(os.path.join(workspace_dir, ".git"))

        deps = _tw()._workspace_deps()
        await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=not reset)

        return {
            "ref": effective_ref,
            "reset": reset,
            "created": not existed,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="ensure_workspace_clone")
