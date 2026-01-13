# Split from github_mcp.tools_workspace (generated).

import os
import posixpath
from typing import Any, Dict, Optional

from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


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
        display_path = os.path.relpath(start, root)
        if display_path == ".":
            display_path = ""
        return display_path, start

    start = os.path.realpath(os.path.join(repo_dir, normalized_path))
    return normalized_path, start


@mcp_tool(write_action=False)
async def list_workspace_files(
    full_name: Optional[str] = None,
    ref: str = "main",
    path: str = "",
    max_files: Optional[int] = None,
    max_results: Optional[int] = None,
    max_depth: Optional[int] = None,
    include_hidden: bool = False,
    include_dirs: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """List files in the workspace clone."""

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
    full_name: Optional[str] = None,
    ref: str = "main",
    query: str = "",
    path: str = "",
    case_sensitive: bool = False,
    max_results: Optional[int] = None,
    regex: Optional[bool] = None,
    max_file_bytes: Optional[int] = None,
    include_hidden: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Search text files in the workspace clone (bounded, no shell).

    Behavior for `query`:
    - Always treated as a literal substring match.
    - `regex` is accepted for compatibility but is not enforced.
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

        used_regex = False
        q = query
        if not case_sensitive:
            q = q.lower()

        def _match_line(line: str) -> bool:
            try:
                hay = line
                if not case_sensitive:
                    hay = hay.lower()
                return q in hay
            except Exception:
                return False

        results: list[dict[str, Any]] = []
        files_scanned = 0
        files_skipped = 0

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
                    os.stat(abs_path)
                except OSError:
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
                    with open(abs_path, "r", encoding="utf-8", errors="ignore") as tf:
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
                except OSError:
                    files_skipped += 1
                    continue

                # max_results is accepted for compatibility/observability but is not
                # enforced as an output limit.

        # Return after scanning the full walk.
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path if path else "",
            "query": query,
            "case_sensitive": case_sensitive,
            "used_regex": used_regex,
            "results": results,
            "truncated": False,
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "max_results": max_results,
            "max_file_bytes": max_file_bytes,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="search_workspace")
