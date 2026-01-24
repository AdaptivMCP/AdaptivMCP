"""Generated repo mirror helpers (workspace clone)."""

from __future__ import annotations

import os
from typing import Any

from github_mcp.server import _structured_tool_error, mcp_tool

from ._shared import _tw


@mcp_tool(
    write_action=True,
    open_world_hint=True,
    destructive_hint=True,
    ui={
        "group": "workspace",
        "icon": "📦",
        "label": "Ensure Workspace Clone",
        "danger": "high",
    },
)
async def ensure_workspace_clone(
    full_name: str | None = None,
    ref: str = "main",
    branch: str | None = None,
    owner: str | None = None,
    repo: str | None = None,
    reset: bool = False,
) -> dict[str, Any]:
    """Ensure a persistent repo mirror (workspace clone) exists for a repo/ref."""

    try:
        resolved_full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        effective_ref = _tw()._effective_ref_for_repo(
            resolved_full_name, _tw()._resolve_ref(ref, branch=branch)
        )
        workspace_dir = _tw()._workspace_path(resolved_full_name, effective_ref)
        existed = os.path.isdir(os.path.join(workspace_dir, ".git"))

        deps = _tw()._workspace_deps()
        await deps["clone_repo"](
            resolved_full_name, ref=effective_ref, preserve_changes=not reset
        )

        return {
            "ref": effective_ref,
            "reset": reset,
            "created": not existed,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="ensure_workspace_clone")
