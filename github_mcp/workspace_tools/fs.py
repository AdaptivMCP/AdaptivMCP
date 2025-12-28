# Split from github_mcp.tools_workspace (generated).
import os
from typing import Any, Dict, Optional

import github_mcp.config as config
from github_mcp.diff_utils import (
    build_unified_diff,
    colorize_unified_diff,
    diff_stats,
    truncate_diff,
)

from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw
    return tw

def _workspace_safe_join(repo_dir: str, rel_path: str) -> str:
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise ValueError("path must be a non-empty string")
    rel_path = rel_path.lstrip("/\\")
    if os.path.isabs(rel_path):
        raise ValueError("path must be relative")

    candidate = os.path.realpath(os.path.join(repo_dir, rel_path))
    root = os.path.realpath(repo_dir)
    if candidate == root or not candidate.startswith(root + os.sep):
        raise ValueError("path escapes repository root")
    return candidate
def _workspace_read_text(repo_dir: str, path: str) -> Dict[str, Any]:
    abs_path = _workspace_safe_join(repo_dir, path)
    if not os.path.exists(abs_path):
        return {
            "exists": False,
            "path": path,
            "text": "",
            "encoding": "utf-8",
            "had_decoding_errors": False,
        }

    with open(abs_path, "rb") as f:
        data = f.read()

    had_errors = False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        had_errors = True
        text = data.decode("utf-8", errors="replace")

    return {
        "exists": True,
        "path": path,
        "text": text,
        "encoding": "utf-8",
        "had_decoding_errors": had_errors,
        "size_bytes": len(data),
    }
def _workspace_write_text(
    repo_dir: str,
    path: str,
    text: str,
    *,
    create_parents: bool = True,
) -> Dict[str, Any]:
    abs_path = _workspace_safe_join(repo_dir, path)
    parent = os.path.dirname(abs_path)
    if create_parents:
        os.makedirs(parent, exist_ok=True)

    existed = os.path.exists(abs_path)
    data = (text or "").encode("utf-8")

    tmp_path = abs_path + ".tmp"
    with open(tmp_path, "wb") as f:
        f.write(data)
    os.replace(tmp_path, abs_path)

    return {
        "path": path,
        "exists_before": existed,
        "size_bytes": len(data),
        "encoding": "utf-8",
    }
@mcp_tool(write_action=False)
async def get_workspace_file_contents(
    full_name: Optional[str] = None,
    ref: str = "main",
    path: str = "",
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Read a file from the persistent workspace clone (no shell)."""

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        info.update({"full_name": full_name, "ref": effective_ref, "repo_dir": repo_dir})
        return info
    except Exception as exc:
        return _structured_tool_error(exc, context="get_workspace_file_contents")
@mcp_tool(write_action=False)
async def set_workspace_file_contents(
    full_name: Optional[str] = None,
    ref: str = "main",
    path: str = "",
    content: str = "",
    create_parents: bool = True,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Replace a workspace file's contents by writing the full file text.

    This is the preferred write primitive for workspace edits. It avoids
    patch/unified-diff application.
    """

    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)

        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        before_info = _workspace_read_text(repo_dir, path)
        before_text = before_info.get("text") if before_info.get("exists") else ""
        write_info = _workspace_write_text(
            repo_dir,
            path,
            content,
            create_parents=create_parents,
        )

        # Render-log friendly diff logging (colored additions/removals).
        full_diff = build_unified_diff(
            before_text or "",
            content or "",
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
        stats = diff_stats(full_diff)

        try:
            config.TOOLS_LOGGER.chat(
                "Workspace wrote %s (+%s -%s)",
                path,
                stats.added,
                stats.removed,
                extra={"repo": full_name, "path": path, "event": "write_diff_summary"},
            )

            if config.TOOLS_LOGGER.isEnabledFor(config.DETAILED_LEVEL) and full_diff.strip():
                truncated = truncate_diff(
                    full_diff,
                    max_lines=config.WRITE_DIFF_LOG_MAX_LINES,
                    max_chars=config.WRITE_DIFF_LOG_MAX_CHARS,
                )
                colored = colorize_unified_diff(truncated)
                config.TOOLS_LOGGER.detailed(
                    "Workspace diff for %s:\n%s",
                    path,
                    colored,
                    extra={"repo": full_name, "path": path, "event": "write_diff"},
                )
        except Exception:
            pass

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "status": "written",
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="set_workspace_file_contents", path=path)
