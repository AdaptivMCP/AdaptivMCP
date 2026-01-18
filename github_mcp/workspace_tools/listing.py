# Split from github_mcp.tools_workspace (generated).

import os
import posixpath
import re
from typing import Any

from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)

from ._shared import _tw


def _normalize_workspace_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    # Collapse dot segments while preserving relative semantics.
    # `posixpath.normpath` is safe here because we already normalized separators.
    normalized = posixpath.normpath(normalized)
    if normalized == ".":
        normalized = ""
    return normalized


def _resolve_workspace_start(repo_dir: str, path: str) -> tuple[str, str]:
    root = os.path.realpath(repo_dir)
    normalized_path = _normalize_workspace_path(path) if path else ""
    if not normalized_path:
        return "", root

    if os.path.isabs(normalized_path):
        start = os.path.realpath(normalized_path)
        try:
            common = os.path.commonpath([root, start])
        except Exception:
            common = ""
        if common != root:
            raise ValueError("path must resolve inside the workspace repository")
        display_path = os.path.relpath(start, root)
        if display_path == ".":
            display_path = ""
        return display_path, start

    start = os.path.realpath(os.path.join(repo_dir, normalized_path))
    try:
        common = os.path.commonpath([root, start])
    except Exception:
        common = ""
    if common != root:
        raise ValueError("path must resolve inside the workspace repository")
    return normalized_path, start


@mcp_tool(write_action=False)
async def list_workspace_files(
    full_name: str | None = None,
    ref: str = "main",
    path: str = "",
    max_files: int | None = None,
    max_results: int | None = None,
    max_depth: int | None = None,
    include_hidden: bool = False,
    include_dirs: bool = False,
    *,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """List files in the repo mirror (workspace clone)."""

    # Alias: some clients use max_results instead of max_files.
    if max_results is not None:
        if max_files is None:
            max_files = max_results
        # If both are provided, keep both values for observability, but do not
        # enforce them as output limits.

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        # Normalize branch/ref the same way as other workspace-backed tools.
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        root = os.path.realpath(repo_dir)
        normalized_path, start = _resolve_workspace_start(repo_dir, path)

        # If path points to a file, return that file (subject to include_hidden).
        if os.path.isfile(start):
            rp = os.path.relpath(start, root)
            if not include_hidden and os.path.basename(rp).startswith("."):
                return {
                    "full_name": full_name,
                    "ref": effective_ref,
                    "path": normalized_path if path else "",
                    "files": [],
                    "truncated": False,
                    "max_files": max_files,
                    "max_depth": max_depth,
                }
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": normalized_path if path else "",
                "files": [rp],
                "truncated": False,
                "max_files": max_files,
                "max_depth": max_depth,
            }

        out: list[str] = []

        for cur_dir, dirnames, filenames in os.walk(start):
            # max_depth is accepted for compatibility/observability but is not
            # enforced as an output limit.

            dirnames[:] = [d for d in dirnames if d != ".git"]
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            if include_dirs:
                for d in dirnames:
                    rp = os.path.relpath(os.path.join(cur_dir, d), root)
                    if not include_hidden and os.path.basename(rp).startswith("."):
                        continue
                    out.append(rp)

            for f in filenames:
                if not include_hidden and f.startswith("."):
                    continue
                rp = os.path.relpath(os.path.join(cur_dir, f), root)
                out.append(rp)

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path if path else "",
            "files": out,
            "truncated": False,
            "max_files": max_files,
            "max_depth": max_depth,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="list_workspace_files")


@mcp_tool(write_action=False)
async def search_workspace(
    full_name: str | None = None,
    ref: str = "main",
    query: str = "",
    path: str = "",
    case_sensitive: bool = False,
    max_results: int | None = None,
    regex: bool | None = None,
    max_file_bytes: int | None = None,
    include_hidden: bool = False,
    *,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Search text files in the repo mirror (workspace clone) (bounded, no shell).

    Behavior for `query`:
    - When regex=true, `query` is treated as a Python regular expression.
    - Otherwise `query` is treated as a literal substring match.
    - Results can be bounded via max_results and files can be bounded via
      max_file_bytes to keep searches responsive on large repositories.
    """

    if not isinstance(query, str) or not query:
        raise ValueError("query must be a non-empty string")

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        root = os.path.realpath(repo_dir)
        normalized_path, start = _resolve_workspace_start(repo_dir, path)

        # Allow searching a single file path.
        single_file = os.path.isfile(start)
        if single_file and (not include_hidden) and os.path.basename(start).startswith("."):
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": normalized_path if path else "",
                "query": query,
                "case_sensitive": case_sensitive,
                "used_regex": False,
                "results": [],
                "truncated": False,
                "files_scanned": 0,
                "files_skipped": 1,
                "max_results": max_results,
                "max_file_bytes": max_file_bytes,
            }

        used_regex = bool(regex)

        q = query
        if not used_regex and (not case_sensitive):
            q = q.lower()

        pattern = None
        if used_regex:
            flags = 0
            if not case_sensitive:
                flags |= re.IGNORECASE
            try:
                pattern = re.compile(query, flags=flags)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern: {exc}") from exc

        def _match_line(line: str) -> bool:
            try:
                if pattern is not None:
                    return pattern.search(line) is not None
                hay = line
                if not case_sensitive:
                    hay = hay.lower()
                return q in hay
            except Exception:
                return False

        results: list[dict[str, Any]] = []
        files_scanned = 0
        files_skipped = 0
        truncated = False

        walk_iter = (
            [(os.path.dirname(start), [], [os.path.basename(start)])]
            if single_file
            else os.walk(start)
        )
        for cur_dir, dirnames, filenames in walk_iter:
            dirnames[:] = [d for d in dirnames if d != ".git"]
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            for fname in filenames:
                if not include_hidden and fname.startswith("."):
                    continue

                abs_path = os.path.join(cur_dir, fname)
                try:
                    st = os.stat(abs_path)
                except OSError:
                    files_skipped += 1
                    continue

                if max_file_bytes is not None and max_file_bytes > 0:
                    try:
                        if st.st_size > max_file_bytes:
                            files_skipped += 1
                            continue
                    except Exception:
                        files_skipped += 1
                        continue

                # max_file_bytes is accepted for compatibility/observability but is not
                # enforced as an output limit.

                # Skip probable binaries.
                try:
                    with open(abs_path, "rb") as bf:
                        sample = bf.read(2048)
                        if b"\x00" in sample:
                            files_skipped += 1
                            continue
                except OSError:
                    files_skipped += 1
                    continue

                files_scanned += 1
                rel_path = os.path.relpath(abs_path, root)

                try:
                    with open(abs_path, encoding="utf-8", errors="ignore") as tf:
                        for i, line in enumerate(tf, start=1):
                            if not _match_line(line):
                                continue

                            results.append(
                                {
                                    "file": rel_path,
                                    "line": i,
                                    "text": line.rstrip("\n"),
                                }
                            )

                            if (
                                max_results is not None
                                and max_results > 0
                                and len(results) >= max_results
                            ):
                                truncated = True
                                break
                except OSError:
                    files_skipped += 1
                    continue

                if truncated:
                    break

                # max_results is accepted for compatibility/observability but is not
                # enforced as an output limit.

            if truncated:
                break

        # Return after scanning the full walk (or truncation).
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path if path else "",
            "query": query,
            "case_sensitive": case_sensitive,
            "used_regex": used_regex,
            "results": results,
            "truncated": truncated,
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "max_results": max_results,
            "max_file_bytes": max_file_bytes,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="search_workspace")
