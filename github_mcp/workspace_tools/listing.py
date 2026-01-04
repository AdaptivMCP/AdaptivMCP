# Split from github_mcp.tools_workspace (generated).

import os
import re
from typing import Any, Dict, Optional

from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


def _path_within_repo(root: str, candidate: str) -> bool:
    root = os.path.realpath(root)
    candidate = os.path.realpath(candidate)
    return candidate == root or candidate.startswith(root + os.sep)


def _normalize_workspace_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    return normalized.lstrip("/")


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
        elif max_files != max_results:
            raise ValueError(
                "max_files and max_results must match when both are provided"
            )

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        root = os.path.realpath(repo_dir)
        normalized_path = _normalize_workspace_path(path) if path else ""
        start = (
            os.path.realpath(os.path.join(repo_dir, normalized_path))
            if normalized_path
            else root
        )
        if not _path_within_repo(root, start):
            raise ValueError("path must stay within repo")

        # If path points to a file, return that file (subject to include_hidden).
        if os.path.isfile(start):
            rp = os.path.relpath(start, root)
            if not include_hidden and os.path.basename(rp).startswith("."):
                return {
                    "full_name": full_name,
                    "ref": effective_ref,
                    "path": normalized_path or path,
                    "files": [],
                    "truncated": False,
                    "max_files": max_files,
                    "max_depth": max_depth,
                }
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": normalized_path or path,
                "files": [rp],
                "truncated": False,
                "max_files": max_files,
                "max_depth": max_depth,
            }

        out: list[str] = []
        truncated = False

        for cur_dir, dirnames, filenames in os.walk(start):
            rel_dir = os.path.relpath(cur_dir, root)
            depth = 0 if rel_dir == os.curdir else rel_dir.count(os.sep) + 1
            if max_depth is not None and max_depth > 0 and depth > max_depth:
                dirnames[:] = []
                continue

            dirnames[:] = [d for d in dirnames if d != ".git"]
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            if include_dirs:
                for d in dirnames:
                    rp = os.path.relpath(os.path.join(cur_dir, d), root)
                    if not include_hidden and os.path.basename(rp).startswith("."):
                        continue
                    out.append(rp)
                    if (
                        max_files is not None
                        and max_files > 0
                        and len(out) >= max_files
                    ):
                        truncated = True
                        break
                if truncated:
                    break

            for f in filenames:
                if not include_hidden and f.startswith("."):
                    continue
                rp = os.path.relpath(os.path.join(cur_dir, f), root)
                out.append(rp)
                if max_files is not None and max_files > 0 and len(out) >= max_files:
                    truncated = True
                    break
            if truncated:
                break

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path or path,
            "files": out,
            "truncated": truncated,
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
      - regex=None (default): treat as regex if valid; if invalid regex, fall back to literal search.
      - regex=False: always literal search (regex metacharacters are escaped).
      - regex=True: strict regex mode (invalid patterns error).
    """

    if not isinstance(query, str) or not query:
        raise ValueError("query must be a non-empty string")

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        root = os.path.realpath(repo_dir)
        normalized_path = _normalize_workspace_path(path) if path else ""
        start = (
            os.path.realpath(os.path.join(repo_dir, normalized_path))
            if normalized_path
            else root
        )
        if not _path_within_repo(root, start):
            raise ValueError("path must stay within repo")

        # Allow searching a single file path.
        single_file = os.path.isfile(start)
        if (
            single_file
            and (not include_hidden)
            and os.path.basename(start).startswith(".")
        ):
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "path": normalized_path or path,
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

        flags = 0 if case_sensitive else re.IGNORECASE

        # Regex/literal handling:
        # - regex=True: strict regex mode (error on invalid pattern)
        # - regex=False: literal substring search
        # - regex=None: try regex; fall back to literal if invalid
        used_regex = True
        pattern = query
        if regex is False:
            used_regex = False
            pattern = re.escape(query)

        try:
            matcher = re.compile(pattern, flags=flags)
        except re.error as exc:
            if regex is True:
                raise ValueError(f"invalid pattern: {exc}") from exc
            # Auto-fallback to literal search when regex is None (default)
            used_regex = False
            pattern = re.escape(query)
            matcher = re.compile(pattern, flags=flags)

        results: list[dict[str, Any]] = []
        truncated = False
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
                    st = os.stat(abs_path)
                except OSError:
                    files_skipped += 1
                    continue

                if (
                    max_file_bytes is not None
                    and max_file_bytes > 0
                    and st.st_size > max_file_bytes
                ):
                    files_skipped += 1
                    continue

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
                            if not matcher.search(line):
                                continue

                            results.append(
                                {
                                    "file": rel_path,
                                    "line": i,
                                    "text": line.rstrip("\n")[:400],
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

            if truncated:
                break

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path or path,
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
