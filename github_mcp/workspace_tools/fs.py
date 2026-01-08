# Split from github_mcp.tools_workspace (generated).
import os
import tempfile

from typing import Any, Dict, Optional

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
    root = os.path.realpath(repo_dir)
    raw_path = rel_path.strip().replace("\\", "/")
    if os.path.isabs(raw_path):
        candidate = os.path.realpath(raw_path)
        if candidate == root or candidate.startswith(root + os.sep):
            return candidate
        raise ValueError("path escapes repository root")
    rel_path = raw_path.lstrip("/\\")
    if not rel_path:
        raise ValueError("path must be a non-empty string")
    candidate = os.path.realpath(os.path.join(repo_dir, rel_path))
    if candidate == root or not candidate.startswith(root + os.sep):
        raise ValueError("path escapes repository root")
    return candidate


def _workspace_read_text(
    repo_dir: str,
    path: str,
    *,
    max_bytes: int = 200_000,
) -> Dict[str, Any]:
    abs_path = _workspace_safe_join(repo_dir, path)
    if not os.path.exists(abs_path):
        return {
            "exists": False,
            "path": path,
            "text": "",
            "encoding": "utf-8",
            "had_decoding_errors": False,
            "content_truncated": False,
            "max_bytes": max_bytes,
        }

    try:
        total_size = os.path.getsize(abs_path)
    except Exception:
        total_size = None

    # Avoid reading arbitrarily large files into memory and returning huge tool
    # payloads. This cap is for the *returned content*, not a permission check.
    if max_bytes is None or max_bytes < 0:
        max_bytes = 200_000

    with open(abs_path, "rb") as f:
        data = f.read(max_bytes + 1)
    truncated = len(data) > max_bytes
    if truncated:
        data = data[:max_bytes]

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
        # Preserve size_bytes as the on-disk size when available.
        "size_bytes": total_size if total_size is not None else len(data),
        "returned_bytes": len(data),
        "content_truncated": truncated,
        "max_bytes": max_bytes,
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
    prev_mode: Optional[int] = None
    if existed:
        try:
            prev_mode = os.stat(abs_path).st_mode
        except Exception:
            prev_mode = None

    data = (text or "").encode("utf-8")

    # Use a unique temp file name in the same directory so os.replace is atomic
    # across filesystems. Avoid fixed suffixes that can collide under concurrent
    # writes.
    fd, tmp_path = tempfile.mkstemp(
        prefix=os.path.basename(abs_path) + ".",
        suffix=".tmp",
        dir=parent,
    )
    try:
        with os.fdopen(fd, "wb") as f:
            fd = -1
            f.write(data)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                # Best-effort durability; atomicity is provided by os.replace.
                pass

        # Preserve the previous file mode when overwriting an existing file.
        if prev_mode is not None:
            try:
                os.chmod(tmp_path, prev_mode)
            except Exception:
                pass

        os.replace(tmp_path, abs_path)

        # Best-effort directory fsync so the rename is durable on POSIX.
        try:
            dir_fd = os.open(parent, os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            pass
    finally:
        if fd not in (-1, None):
            try:
                os.close(fd)
            except Exception:
                pass
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

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
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        try:
            max_bytes = int(os.environ.get("MCP_WORKSPACE_FILE_MAX_BYTES", "200000"))
        except Exception:
            max_bytes = 200_000

        info = _workspace_read_text(repo_dir, path, max_bytes=max_bytes)
        info.update({"full_name": full_name, "ref": effective_ref})
        return info
    except Exception as exc:
        return _structured_tool_error(exc, context="get_workspace_file_contents")


@mcp_tool(write_action=True)
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

        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )
        write_info = _workspace_write_text(
            repo_dir,
            path,
            content,
            create_parents=create_parents,
        )

        return {
            "branch": effective_ref,
            "status": "written",
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc, context="set_workspace_file_contents", path=path
        )


@mcp_tool(write_action=True)
async def apply_patch(
    full_name: Optional[str] = None,
    ref: str = "main",
    patch: str = "",
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a unified diff patch to the persistent workspace clone."""

    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("patch must be a non-empty string")

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )
        await deps["apply_patch_to_repo"](repo_dir, patch)
        return {"branch": effective_ref, "status": "patched"}
    except Exception as exc:
        return _structured_tool_error(exc, context="apply_patch")
