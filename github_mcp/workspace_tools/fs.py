# Split from github_mcp.tools_workspace (generated).
import os
import shutil
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from github_mcp.diff_utils import build_unified_diff

from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


_LOG_WRITE_DIFFS = os.environ.get("GITHUB_MCP_LOG_WRITE_DIFFS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
_LOG_WRITE_DIFFS_MAX_CHARS = int(os.environ.get("GITHUB_MCP_LOG_WRITE_DIFFS_MAX_CHARS", "120000"))
_LOG_WRITE_DIFFS_MAX_FILE_CHARS = int(
    os.environ.get("GITHUB_MCP_LOG_WRITE_DIFFS_MAX_FILE_CHARS", "250000")
)


def _maybe_diff_for_log(
    *,
    path: str,
    before: str,
    after: str,
    before_exists: bool,
) -> str | None:
    """Best-effort unified diff for provider logs.

    The diff is attached to tool results under a __log_* key and stripped from
    client-visible payloads by the tool wrapper.
    """

    if not _LOG_WRITE_DIFFS:
        return None
    if not isinstance(before, str) or not isinstance(after, str):
        return None
    # Avoid expensive diffs for huge files.
    if (
        len(before) > _LOG_WRITE_DIFFS_MAX_FILE_CHARS
        or len(after) > _LOG_WRITE_DIFFS_MAX_FILE_CHARS
    ):
        return None
    if before == after:
        return None

    diff = build_unified_diff(
        before,
        after,
        fromfile=(path if before_exists else "/dev/null"),
        tofile=path,
    )
    if not diff:
        return None
    if len(diff) > _LOG_WRITE_DIFFS_MAX_CHARS:
        diff = diff[:_LOG_WRITE_DIFFS_MAX_CHARS] + "\n… (diff truncated)\n"
    return diff


def _delete_diff_for_log(*, path: str, before: str) -> str | None:
    """Best-effort unified diff for deletions."""

    if not _LOG_WRITE_DIFFS:
        return None
    if not isinstance(before, str) or before == "":
        return None
    if len(before) > _LOG_WRITE_DIFFS_MAX_FILE_CHARS:
        return None
    diff = build_unified_diff(before, "", fromfile=path, tofile="/dev/null")
    if not diff:
        return None
    if len(diff) > _LOG_WRITE_DIFFS_MAX_CHARS:
        diff = diff[:_LOG_WRITE_DIFFS_MAX_CHARS] + "\n… (diff truncated)\n"
    return diff


def _looks_like_diff(text: str) -> bool:
    if not isinstance(text, str):
        return False
    s = text.lstrip()
    if not s:
        return False
    sample = "\n".join(s.splitlines()[:25])
    return (
        "diff --git" in sample
        or sample.startswith("diff --git")
        or "+++ " in sample
        or "--- " in sample
        or "@@ " in sample
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
        # For consistent tool UX (and to reduce ambiguity around workspace base
        # directories), require repository-relative paths. All workspace file
        # tools accept paths relative to the repo mirror root.
        raise ValueError("path must be repository-relative (no leading '/')")
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


def _infer_eol_from_lines(lines: List[str]) -> str:
    """Infer an EOL sequence from an existing file.

    Defaults to \n, but prefers \r\n when detected.
    """

    for line in lines:
        if line.endswith("\r\n"):
            return "\r\n"
    for line in lines:
        if line.endswith("\n"):
            return "\n"
    for line in lines:
        if line.endswith("\r"):
            return "\r"
    return "\n"


def _split_lines_keepends(text: str) -> List[str]:
    # splitlines(True) returns [] for empty strings; keep that behavior.
    return (text or "").splitlines(True)


def _line_content_and_eol(raw_line: str) -> Tuple[str, str]:
    if raw_line.endswith("\r\n"):
        return raw_line[:-2], "\r\n"
    if raw_line.endswith("\n"):
        return raw_line[:-1], "\n"
    if raw_line.endswith("\r"):
        return raw_line[:-1], "\r"
    return raw_line, ""


def _pos_to_offset(lines: List[str], line: int, col: int) -> int:
    """Convert a 1-indexed (line, col) position to a 0-indexed absolute offset.

    Semantics:
      - line is 1..len(lines)+1 (len(lines)+1 represents EOF).
      - col is 1..len(line_content)+1 for in-file lines.
      - For EOF (line == len(lines)+1), col must be 1.
      - col counts unicode codepoints within the line content; the position
        col=len(content)+1 is the point *after* the last character in that line,
        but before the line ending (if any). Selecting across lines naturally
        includes the newline by using end=(next_line, 1).
    """

    if line < 1:
        raise ValueError("line must be >= 1")
    if col < 1:
        raise ValueError("col must be >= 1")

    # EOF sentinel.
    if line == len(lines) + 1:
        if col != 1:
            raise ValueError("col must be 1 when line points at EOF")
        return sum(len(x) for x in lines)

    if line > len(lines):
        raise ValueError("line out of range")

    raw_line = lines[line - 1]
    content, _eol = _line_content_and_eol(raw_line)
    if col > len(content) + 1:
        raise ValueError("col out of range for line")

    prefix = sum(len(x) for x in lines[: line - 1])
    return prefix + (col - 1)


@mcp_tool(write_action=True)
async def delete_workspace_paths(
    full_name: str,
    ref: str = "main",
    paths: List[str] | None = None,
    allow_missing: bool = True,
    allow_recursive: bool = False,
) -> Dict[str, Any]:
    """Delete one or more paths from the repo mirror.

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
    """Read a file from the persistent repo mirror (no shell).

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

    This is a good fit for repo-mirror edits when you want to replace the full
    contents of a file without relying on unified-diff patch application.
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
        before_info = _workspace_read_text(repo_dir, path)
        before_text = (before_info.get("text") or "") if before_info.get("exists") else ""
        write_info = _workspace_write_text(
            repo_dir,
            path,
            content,
            create_parents=create_parents,
        )

        log_diff = _maybe_diff_for_log(
            path=path,
            before=before_text,
            after=content,
            before_exists=bool(before_info.get("exists")),
        )

        return {
            "ref": effective_ref,
            "status": "written",
            "__log_diff": log_diff,
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="set_workspace_file_contents", path=path)


@mcp_tool(write_action=True)
async def edit_workspace_text_range(
    full_name: str,
    ref: str = "main",
    path: str = "",
    start_line: int = 1,
    start_col: int = 1,
    end_line: int = 1,
    end_col: int = 1,
    replacement: str = "",
    create_parents: bool = True,
) -> Dict[str, Any]:
    """Edit a file by replacing a precise (line, column) text range.

    This is the most granular edit primitive:
      - Single-character edit: start=(L,C), end=(L,C+1)
      - Word edit: start/end wrap the word
      - Line edit: start=(L,1), end=(L+1,1) (includes the newline)

    Positions are 1-indexed. The end position is *exclusive* (Python-slice
    semantics).
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if replacement is None:
            replacement = ""
        if not isinstance(replacement, str):
            raise TypeError("replacement must be a string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        lines = _split_lines_keepends(original)

        start_offset = _pos_to_offset(lines, int(start_line), int(start_col))
        end_offset = _pos_to_offset(lines, int(end_line), int(end_col))
        if end_offset < start_offset:
            raise ValueError("end position must be after or equal to start position")

        updated = original[:start_offset] + replacement + original[end_offset:]
        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )

        log_diff = _maybe_diff_for_log(
            path=path,
            before=original,
            after=updated,
            before_exists=True,
        )

        return {
            "ref": effective_ref,
            "status": "edited",
            "path": path,
            "start": {"line": int(start_line), "col": int(start_col)},
            "end": {"line": int(end_line), "col": int(end_col)},
            "bytes_before": len(original.encode("utf-8")),
            "bytes_after": len(updated.encode("utf-8")),
            "__log_diff": log_diff,
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="edit_workspace_text_range",
            path=path,
            start_line=start_line,
            start_col=start_col,
            end_line=end_line,
            end_col=end_col,
        )


@mcp_tool(write_action=True)
async def edit_workspace_line(
    full_name: str,
    ref: str = "main",
    path: str = "",
    operation: Literal["replace", "insert_before", "insert_after", "delete"] = "replace",
    line_number: int = 1,
    text: str = "",
    create_parents: bool = True,
) -> Dict[str, Any]:
    """Edit a single line in a workspace file.

    Operations:
      - replace: replace the target line's content (preserves its line ending).
      - insert_before / insert_after: insert a new line adjacent to line_number.
      - delete: delete the target line.

    Line numbers are 1-indexed.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if operation not in ("replace", "insert_before", "insert_after", "delete"):
            raise ValueError("operation must be replace/insert_before/insert_after/delete")
        if not isinstance(line_number, int) or line_number < 1:
            raise ValueError("line_number must be an int >= 1")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise TypeError("text must be a string")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        lines = _split_lines_keepends(original)
        eol = _infer_eol_from_lines(lines)

        if line_number > max(1, len(lines)):
            raise ValueError("line_number out of range")

        def _ensure_eol(s: str) -> str:
            if s.endswith("\r\n") or s.endswith("\n") or s.endswith("\r"):
                return s
            return s + eol

        idx = line_number - 1

        if operation == "delete":
            if not lines:
                raise ValueError("cannot delete from an empty file")
            removed = lines.pop(idx)
            updated_lines = lines
            updated = "".join(updated_lines)
            write_info = _workspace_write_text(
                repo_dir,
                path,
                updated,
                create_parents=create_parents,
            )
            return {
                "ref": effective_ref,
                "status": "edited",
                "path": path,
                "operation": operation,
                "line_number": line_number,
                "removed": removed,
                "line_count_before": len(_split_lines_keepends(original)),
                "line_count_after": len(updated_lines),
                "__log_diff": _maybe_diff_for_log(
                    path=path,
                    before=original,
                    after=updated,
                    before_exists=True,
                ),
                **write_info,
            }

        if operation in ("insert_before", "insert_after"):
            insert_at = idx if operation == "insert_before" else idx + 1
            payload = text
            payload = _ensure_eol(payload)
            lines.insert(insert_at, payload)
            updated = "".join(lines)
            write_info = _workspace_write_text(
                repo_dir,
                path,
                updated,
                create_parents=create_parents,
            )
            return {
                "ref": effective_ref,
                "status": "edited",
                "path": path,
                "operation": operation,
                "line_number": line_number,
                "inserted_at": insert_at + 1,
                "inserted": payload,
                "line_count_before": len(_split_lines_keepends(original)),
                "line_count_after": len(lines),
                "__log_diff": _maybe_diff_for_log(
                    path=path,
                    before=original,
                    after=updated,
                    before_exists=True,
                ),
                **write_info,
            }

        # replace
        if not lines:
            # Empty file: treat line 1 as replaceable.
            payload = _ensure_eol(text)
            updated = payload
        else:
            raw = lines[idx]
            _content, line_eol = _line_content_and_eol(raw)
            # Preserve the existing line ending (or fallback to inferred).
            effective_eol = line_eol or eol
            payload = text
            payload = payload.rstrip("\r\n")
            payload = payload + effective_eol if effective_eol else payload
            lines[idx] = payload
            updated = "".join(lines)

        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )
        return {
            "ref": effective_ref,
            "status": "edited",
            "path": path,
            "operation": operation,
            "line_number": line_number,
            "line_count_before": len(_split_lines_keepends(original)),
            "line_count_after": len(_split_lines_keepends(updated)),
            "__log_diff": _maybe_diff_for_log(
                path=path,
                before=original,
                after=updated,
                before_exists=True,
            ),
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="edit_workspace_line",
            path=path,
            operation=operation,
            line_number=line_number,
        )


@mcp_tool(write_action=True)
async def replace_workspace_text(
    full_name: str,
    ref: str = "main",
    path: str = "",
    old: str = "",
    new: str = "",
    occurrence: int = 1,
    replace_all: bool = False,
    create_parents: bool = True,
) -> Dict[str, Any]:
    """Replace text in a workspace file (single word/character or substring).

    By default, replaces the Nth occurrence (1-indexed). Use replace_all=true
    to replace all occurrences.
    """

    try:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(old, str) or old == "":
            raise ValueError("old must be a non-empty string")
        if new is None:
            new = ""
        if not isinstance(new, str):
            raise TypeError("new must be a string")
        if not isinstance(occurrence, int) or occurrence < 1:
            raise ValueError("occurrence must be an int >= 1")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        if not info.get("exists"):
            raise FileNotFoundError(path)

        original = info.get("text") or ""
        updated = original
        replaced = 0

        if replace_all:
            replaced = original.count(old)
            updated = original.replace(old, new)
        else:
            start = 0
            found_at = -1
            for _i in range(occurrence):
                found_at = original.find(old, start)
                if found_at == -1:
                    break
                start = found_at + len(old)
            if found_at != -1:
                replaced = 1
                updated = original[:found_at] + new + original[found_at + len(old) :]

        if replaced == 0:
            return {
                "ref": effective_ref,
                "status": "noop",
                "path": path,
                "replaced": 0,
                "replace_all": bool(replace_all),
                "occurrence": int(occurrence),
            }

        write_info = _workspace_write_text(
            repo_dir,
            path,
            updated,
            create_parents=create_parents,
        )

        return {
            "ref": effective_ref,
            "status": "replaced",
            "path": path,
            "replaced": replaced,
            "replace_all": bool(replace_all),
            "occurrence": int(occurrence),
            "__log_diff": _maybe_diff_for_log(
                path=path,
                before=original,
                after=updated,
                before_exists=True,
            ),
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(
            exc,
            context="replace_workspace_text",
            path=path,
            occurrence=occurrence,
            replace_all=replace_all,
        )


@mcp_tool(write_action=True)
async def apply_patch(
    full_name: str,
    ref: str = "main",
    patch: str = "",
) -> Dict[str, Any]:
    """Apply a unified diff patch to the persistent repo mirror."""

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


@mcp_tool(write_action=True)
async def move_workspace_paths(
    full_name: str,
    ref: str = "main",
    moves: List[Dict[str, Any]] | None = None,
    overwrite: bool = False,
    create_parents: bool = True,
) -> Dict[str, Any]:
    """Move (rename) one or more workspace paths inside the repo mirror.

    Args:
      moves: list of {"src": "path", "dst": "path"}
      overwrite: if true, allow replacing an existing destination.
    """

    if moves is None:
        moves = []
    if not isinstance(moves, list) or any(not isinstance(m, dict) for m in moves):
        raise TypeError("moves must be a list of dicts")
    if not moves:
        raise ValueError("moves must contain at least one item")

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        moved: List[Dict[str, str]] = []
        failed: List[Dict[str, Any]] = []

        for m in moves:
            src = m.get("src")
            dst = m.get("dst")
            if not isinstance(src, str) or not src.strip():
                failed.append({"src": src, "dst": dst, "error": "src must be a non-empty string"})
                continue
            if not isinstance(dst, str) or not dst.strip():
                failed.append({"src": src, "dst": dst, "error": "dst must be a non-empty string"})
                continue

            try:
                abs_src = _workspace_safe_join(repo_dir, src)
                abs_dst = _workspace_safe_join(repo_dir, dst)
                if not os.path.exists(abs_src):
                    raise FileNotFoundError(src)
                if os.path.exists(abs_dst):
                    if overwrite:
                        if os.path.isdir(abs_dst):
                            shutil.rmtree(abs_dst)
                        else:
                            os.remove(abs_dst)
                    else:
                        raise FileExistsError(dst)

                if create_parents:
                    os.makedirs(os.path.dirname(abs_dst), exist_ok=True)

                shutil.move(abs_src, abs_dst)
                moved.append({"src": src, "dst": dst})
            except Exception as exc:
                failed.append({"src": src, "dst": dst, "error": str(exc)})

        return {
            "ref": effective_ref,
            "status": "moved",
            "moved": moved,
            "failed": failed,
            "ok": len(failed) == 0,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="move_workspace_paths")


@mcp_tool(write_action=True)
async def apply_workspace_operations(
    full_name: str,
    ref: str = "main",
    operations: List[Dict[str, Any]] | None = None,
    fail_fast: bool = True,
    rollback_on_error: bool = True,
    preview_only: bool = False,
    create_parents: bool = True,
) -> Dict[str, Any]:
    """Apply multiple file operations in a single workspace clone.

    This is a higher-level, multi-file alternative to calling the single-file
    primitives repeatedly.

    Supported operations (each item in `operations`):
      - {"op": "write", "path": "...", "content": "..."}
      - {"op": "replace_text", "path": "...", "old": "...", "new": "...", "replace_all": bool, "occurrence": int}
      - {"op": "edit_range", "path": "...", "start": {"line": int, "col": int}, "end": {"line": int, "col": int}, "replacement": "..."}
      - {"op": "delete", "path": "...", "allow_missing": bool}
      - {"op": "move", "src": "...", "dst": "...", "overwrite": bool}
      - {"op": "apply_patch", "patch": "..."}
    """

    if operations is None:
        operations = []
    if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
        raise TypeError("operations must be a list of dicts")
    if not operations:
        raise ValueError("operations must contain at least one item")

    def _read_bytes(path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def _write_bytes(path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    # Best-effort rollback by restoring prior file bytes.
    backups: Dict[str, Optional[bytes]] = {}

    def _backup_path(abs_path: str) -> None:
        if abs_path in backups:
            return
        if os.path.exists(abs_path):
            backups[abs_path] = _read_bytes(abs_path)
        else:
            backups[abs_path] = None

    def _restore_backups() -> None:
        for abs_path, data in backups.items():
            try:
                if data is None:
                    if os.path.exists(abs_path):
                        if os.path.isdir(abs_path):
                            shutil.rmtree(abs_path)
                        else:
                            os.remove(abs_path)
                    continue
                _write_bytes(abs_path, data)
            except Exception:
                # Best-effort rollback.
                pass

    try:
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        results: List[Dict[str, Any]] = []
        diffs: List[str] = []

        for idx, op in enumerate(operations):
            op_name = op.get("op")
            if not isinstance(op_name, str) or not op_name.strip():
                entry = {"index": idx, "status": "error", "error": "op must be a non-empty string"}
                results.append(entry)
                if fail_fast:
                    raise ValueError(entry["error"])
                continue

            try:
                if op_name == "write":
                    path = op.get("path")
                    content = op.get("content")
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("write.path must be a non-empty string")
                    if content is None:
                        content = ""
                    if not isinstance(content, str):
                        raise TypeError("write.content must be a string")

                    abs_path = _workspace_safe_join(repo_dir, path)
                    _backup_path(abs_path)
                    before = backups[abs_path].decode("utf-8", errors="replace") if backups[abs_path] else ""
                    after = content
                    if not preview_only:
                        _workspace_write_text(repo_dir, path, content, create_parents=create_parents)
                    d = _maybe_diff_for_log(path=path, before=before, after=after, before_exists=backups[abs_path] is not None)
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append({"index": idx, "op": "write", "path": path, "status": "ok"})
                    continue

                if op_name == "replace_text":
                    path = op.get("path")
                    old = op.get("old")
                    new = op.get("new")
                    replace_all = bool(op.get("replace_all", False))
                    occurrence = int(op.get("occurrence", 1) or 1)
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("replace_text.path must be a non-empty string")
                    if not isinstance(old, str) or old == "":
                        raise ValueError("replace_text.old must be a non-empty string")
                    if new is None:
                        new = ""
                    if not isinstance(new, str):
                        raise TypeError("replace_text.new must be a string")

                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(path)
                    _backup_path(abs_path)
                    before = backups[abs_path].decode("utf-8", errors="replace") if backups[abs_path] else ""

                    if replace_all:
                        after = before.replace(old, new)
                    else:
                        start = 0
                        found_at = -1
                        for _i in range(max(1, occurrence)):
                            found_at = before.find(old, start)
                            if found_at == -1:
                                break
                            start = found_at + len(old)
                        after = before
                        if found_at != -1:
                            after = before[:found_at] + new + before[found_at + len(old) :]

                    if not preview_only and after != before:
                        _workspace_write_text(repo_dir, path, after, create_parents=create_parents)
                    d = _maybe_diff_for_log(path=path, before=before, after=after, before_exists=True)
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append(
                        {
                            "index": idx,
                            "op": "replace_text",
                            "path": path,
                            "status": "ok" if after != before else "noop",
                        }
                    )
                    continue

                if op_name == "edit_range":
                    path = op.get("path")
                    start = op.get("start")
                    end = op.get("end")
                    replacement = op.get("replacement")
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("edit_range.path must be a non-empty string")
                    if replacement is None:
                        replacement = ""
                    if not isinstance(replacement, str):
                        raise TypeError("edit_range.replacement must be a string")
                    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
                        raise TypeError("edit_range.start/end must be objects")
                    start_line = int(start.get("line"))
                    start_col = int(start.get("col"))
                    end_line = int(end.get("line"))
                    end_col = int(end.get("col"))

                    abs_path = _workspace_safe_join(repo_dir, path)
                    if not os.path.exists(abs_path):
                        raise FileNotFoundError(path)
                    _backup_path(abs_path)
                    before = backups[abs_path].decode("utf-8", errors="replace") if backups[abs_path] else ""
                    lines = _split_lines_keepends(before)
                    start_offset = _pos_to_offset(lines, start_line, start_col)
                    end_offset = _pos_to_offset(lines, end_line, end_col)
                    if end_offset < start_offset:
                        raise ValueError("edit_range.end must be after start")
                    after = before[:start_offset] + replacement + before[end_offset:]

                    if not preview_only and after != before:
                        _workspace_write_text(repo_dir, path, after, create_parents=create_parents)
                    d = _maybe_diff_for_log(path=path, before=before, after=after, before_exists=True)
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    results.append(
                        {
                            "index": idx,
                            "op": "edit_range",
                            "path": path,
                            "status": "ok" if after != before else "noop",
                        }
                    )
                    continue

                if op_name == "delete":
                    path = op.get("path")
                    allow_missing = bool(op.get("allow_missing", True))
                    if not isinstance(path, str) or not path.strip():
                        raise ValueError("delete.path must be a non-empty string")
                    abs_path = _workspace_safe_join(repo_dir, path)
                    _backup_path(abs_path)
                    if backups[abs_path] is None:
                        if allow_missing:
                            results.append({"index": idx, "op": "delete", "path": path, "status": "noop"})
                            continue
                        raise FileNotFoundError(path)

                    before = backups[abs_path].decode("utf-8", errors="replace") if backups[abs_path] else ""
                    d = _delete_diff_for_log(path=path, before=before)
                    if isinstance(d, str) and d:
                        diffs.append(d)
                    if not preview_only:
                        os.remove(abs_path)
                    results.append({"index": idx, "op": "delete", "path": path, "status": "ok"})
                    continue

                if op_name == "move":
                    src = op.get("src")
                    dst = op.get("dst")
                    overwrite = bool(op.get("overwrite", False))
                    if not isinstance(src, str) or not src.strip():
                        raise ValueError("move.src must be a non-empty string")
                    if not isinstance(dst, str) or not dst.strip():
                        raise ValueError("move.dst must be a non-empty string")
                    abs_src = _workspace_safe_join(repo_dir, src)
                    abs_dst = _workspace_safe_join(repo_dir, dst)
                    if not os.path.exists(abs_src):
                        raise FileNotFoundError(src)
                    _backup_path(abs_src)
                    _backup_path(abs_dst)
                    if os.path.exists(abs_dst) and not overwrite:
                        raise FileExistsError(dst)
                    if not preview_only:
                        if os.path.exists(abs_dst) and overwrite:
                            if os.path.isdir(abs_dst):
                                shutil.rmtree(abs_dst)
                            else:
                                os.remove(abs_dst)
                        if create_parents:
                            os.makedirs(os.path.dirname(abs_dst), exist_ok=True)
                        shutil.move(abs_src, abs_dst)
                    results.append({"index": idx, "op": "move", "src": src, "dst": dst, "status": "ok"})
                    continue

                if op_name == "apply_patch":
                    patch = op.get("patch")
                    if not isinstance(patch, str) or not patch.strip():
                        raise ValueError("apply_patch.patch must be a non-empty string")
                    if not preview_only:
                        await deps["apply_patch_to_repo"](repo_dir, patch)
                    # Prefer letting the provider visual handler render this patch directly.
                    if _looks_like_diff(patch):
                        diffs.append(patch)
                    results.append({"index": idx, "op": "apply_patch", "status": "ok"})
                    continue

                raise ValueError(f"Unsupported op: {op_name}")

            except Exception as exc:
                entry = {"index": idx, "op": op_name, "status": "error", "error": str(exc)}
                results.append(entry)
                if fail_fast:
                    raise

        ok = all(r.get("status") not in {"error"} for r in results)
        combined_diff = "\n".join(diffs).strip() if diffs else None
        if combined_diff and not combined_diff.endswith("\n"):
            combined_diff += "\n"

        return {
            "ref": effective_ref,
            "status": "ok" if ok else "partial",
            "ok": ok,
            "preview_only": bool(preview_only),
            "results": results,
            "__log_diff": combined_diff,
        }

    except Exception as exc:
        if rollback_on_error and backups:
            try:
                _restore_backups()
            except Exception:
                pass
        return _structured_tool_error(exc, context="apply_workspace_operations")
