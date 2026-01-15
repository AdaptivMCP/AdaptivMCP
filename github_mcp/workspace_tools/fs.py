# Split from github_mcp.tools_workspace (generated).
import os
import shutil
from typing import Any, Dict, List

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
    raw_path = rel_path.strip().replace("\\", "/")
    root = os.path.realpath(repo_dir)
    if os.path.isabs(raw_path):
        candidate = os.path.realpath(raw_path)
        # Allow absolute paths only when they resolve inside the workspace.
        try:
            common = os.path.commonpath([root, candidate])
        except Exception:
            common = ""
        if common != root:
            raise ValueError("path must resolve inside the workspace repository")
        return candidate
    rel_path = raw_path.lstrip("/\\")
    if not rel_path:
        raise ValueError("path must be a non-empty string")
    candidate = os.path.realpath(os.path.join(repo_dir, rel_path))
    try:
        common = os.path.commonpath([root, candidate])
    except Exception:
        common = ""
    if common != root:
        raise ValueError("path must resolve inside the workspace repository")
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


@mcp_tool(write_action=True)
async def delete_workspace_paths(
    full_name: str,
    ref: str = "main",
    paths: List[str] | None = None,
    allow_missing: bool = True,
    allow_recursive: bool = False,
) -> Dict[str, Any]:
    """Delete one or more paths from the repo mirror (workspace clone).

    This tool exists because some environments can block patch-based file deletions.
    Prefer this over embedding deletions into unified-diff patches.

    Notes:
      - `paths` must be repo-relative paths.
      - Directories require `allow_recursive=true` (for non-empty directories).
    """

    if paths is None:
        paths = []
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise TypeError("paths must be a list of strings")
    if len(paths) == 0:
        raise ValueError("paths must contain at least one path")

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)

        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        removed: List[str] = []
        missing: List[str] = []
        failed: List[Dict[str, Any]] = []

        for rel_path in paths:
            try:
                abs_path = _workspace_safe_join(repo_dir, rel_path)

                if not os.path.exists(abs_path):
                    if allow_missing:
                        missing.append(rel_path)
                        continue
                    raise FileNotFoundError(rel_path)

                if os.path.isdir(abs_path):
                    if allow_recursive:
                        shutil.rmtree(abs_path)
                    else:
                        os.rmdir(abs_path)
                else:
                    os.remove(abs_path)

                removed.append(rel_path)
            except Exception as exc:
                failed.append({"path": rel_path, "error": str(exc)})

        return {
            "ref": effective_ref,
            "status": "deleted",
            "removed": removed,
            "missing": missing,
            "failed": failed,
            "ok": len(failed) == 0,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="delete_workspace_paths")


@mcp_tool(write_action=False)
async def get_workspace_file_contents(
    full_name: str,
    ref: str = "main",
    path: str = "",
) -> Dict[str, Any]:
    """Read a file from the persistent repo mirror (workspace clone) (no shell).

    Args:
      path: Repo-relative path (POSIX-style). Must resolve inside the repo mirror.

    Returns:
      A dict with keys like: exists, path, text, encoding, size_bytes.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        info.update({"full_name": full_name, "ref": effective_ref})
        return info
    except Exception as exc:
        return _structured_tool_error(exc, context="get_workspace_file_contents", path=path)


@mcp_tool(write_action=True)
async def set_workspace_file_contents(
    full_name: str,
    ref: str = "main",
    path: str = "",
    content: str = "",
    create_parents: bool = True,
) -> Dict[str, Any]:
    """Replace a workspace file's contents by writing the full file text.

    This is the preferred write primitive for workspace edits in the repo mirror. It avoids
    patch/unified-diff application.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if content is None:
            content = ""
        if not isinstance(content, str):
            raise TypeError("content must be a string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)

        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        write_info = _workspace_write_text(
            repo_dir,
            path,
            content,
            create_parents=create_parents,
        )

        return {
            "ref": effective_ref,
            "status": "written",
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="set_workspace_file_contents", path=path)


@mcp_tool(write_action=True)
async def apply_patch(
    full_name: str,
    ref: str = "main",
    patch: str = "",
) -> Dict[str, Any]:
    """Apply a unified diff patch to the persistent repo mirror (workspace clone)."""

    try:
        if not isinstance(patch, str) or not patch.strip():
            raise ValueError("patch must be a non-empty string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        await deps["apply_patch_to_repo"](repo_dir, patch)
        return {"ref": effective_ref, "status": "patched"}
    except Exception as exc:
        return _structured_tool_error(exc, context="apply_patch")
