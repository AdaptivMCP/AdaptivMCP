# Split from github_mcp.tools_workspace (generated).
import os
from typing import Any, Dict, Optional

from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


@mcp_tool(write_action=True)
async def ensure_workspace_clone(
    full_name: Optional[str] = None,
    ref: str = "main",
    reset: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Ensure a persistent workspace clone exists for a repo/ref."""

    try:
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        workspace_dir = _tw()._workspace_path(full_name, effective_ref)
        existed = os.path.isdir(os.path.join(workspace_dir, ".git"))

        deps = _tw()._workspace_deps()
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=not reset
        )

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "reset": reset,
            "created": not existed,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="ensure_workspace_clone")
