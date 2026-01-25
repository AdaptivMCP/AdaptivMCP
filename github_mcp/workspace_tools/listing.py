# Split from github_mcp.tools_workspace (generated).

import hashlib
import os
import posixpath
import re
from typing import Any

from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)

from ._shared import _tw


def _is_probably_binary(path: str) -> bool:
    try:
        with open(path, "rb") as bf:
            sample = bf.read(4096)
        return b"\x00" in sample
    except OSError:
        return False


def _sha256_limited(path: str, *, max_bytes: int) -> tuple[str | None, bool]:
    """Return (sha256_hex, truncated) for the first max_bytes of a file."""
    h = hashlib.sha256()
    read = 0
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(min(65536, max_bytes - read))
                if not chunk:
                    break
                h.update(chunk)
                read += len(chunk)
                if read >= max_bytes:
                    break
        truncated = False
        try:
            truncated = os.path.getsize(path) > max_bytes
        except Exception:
            truncated = False
        return h.hexdigest(), truncated
    except OSError:
        return None, False


def _count_lines_limited(path: str, *, max_bytes: int) -> tuple[int | None, bool]:
    """Return (line_count, truncated).

    Counts lines from the first max_bytes bytes (UTF-8 decode with replacement).
    """
    read = 0
    lines = 0
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(min(65536, max_bytes - read))
                if not chunk:
                    break
                read += len(chunk)
                lines += chunk.count(b"\n")
                if read >= max_bytes:
                    break
        truncated = False
        try:
            truncated = os.path.getsize(path) > max_bytes
        except Exception:
            truncated = False
        # If file does not end with newline, approximate by +1 when non-empty.
        if lines == 0:
            try:
                if os.path.getsize(path) > 0:
                    lines = 1
            except Exception:
                pass
        return int(lines), truncated
    except OSError:
        return None, False


def _read_first_lines(
    path: str, *, max_lines: int, max_chars: int
) -> tuple[list[dict[str, Any]], bool]:
    """Return (lines, truncated) where lines are {line, text} starting at 1."""
    out: list[dict[str, Any]] = []
    truncated = False
    chars = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, raw in enumerate(f, start=1):
                if i > max_lines:
                    truncated = True
                    break
                text = raw.rstrip("\n")
                next_chars = chars + len(text) + 1
                if next_chars > max_chars:
                    truncated = True
                    break
                out.append({"line": i, "text": text})
                chars = next_chars
    except OSError:
        return [], False
    return out, truncated


def _normalize_workspace_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    # Collapse dot segments while preserving relative semantics.
    # `posixpath.normpath` is safe here because we already normalized separators.
    normalized = posixpath.normpath(normalized)
    if normalized in (".", "/"):
        return ""

    # Be permissive with parent-directory segments in *relative* paths.
    # LLM clients often produce "../" paths; clamp them safely back into the
    # workspace root rather than hard-failing.
    #
    # Safety invariant is still enforced later when we resolve against repo_dir.
    if not normalized.startswith("/"):
        parts: list[str] = []
        for part in normalized.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                # Clamp attempts to traverse beyond root.
                continue
            parts.append(part)
        normalized = "/".join(parts)
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
            # Heuristic fallback: many callers send "/subdir" intending a
            # repo-relative path. If the absolute path doesn't resolve inside
            # the workspace root, try interpreting it as repo-relative.
            rel = normalized_path.lstrip("/")
            if not rel:
                return "", root
            start = os.path.realpath(os.path.join(repo_dir, rel))
            try:
                common = os.path.commonpath([root, start])
            except Exception:
                common = ""
            if common != root:
                raise ValueError("path must resolve inside the workspace repository")
            return rel, start
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
    include_hidden: bool = True,
    include_dirs: bool = False,
    cursor: int = 0,
    *,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """List files in the repo mirror (workspace clone).

    This endpoint is designed to work for very large repos:
    - Enforces `max_files` and `max_depth` (unlike earlier versions).
    - Supports simple pagination via `cursor` (an integer offset).
    """

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
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

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

        # Output limits.
        if max_files is None:
            max_files = 5000
        if not isinstance(max_files, int) or max_files < 1:
            raise ValueError("max_files must be an int >= 1")
        if max_depth is None:
            max_depth = 25
        if not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be an int >= 0")

        # Cursor is a simple offset in the ordered result stream.
        if not isinstance(cursor, int) or cursor < 0:
            raise ValueError("cursor must be an int >= 0")
        cursor = int(cursor)

        out: list[str] = []
        skipped = 0
        yielded = 0
        next_cursor: int | None = None
        truncated = False

        def _depth_for_dir(cur_dir: str) -> int:
            rel = os.path.relpath(cur_dir, start)
            if rel in {".", ""}:
                return 0
            return rel.count(os.sep) + 1

        for cur_dir, dirnames, filenames in os.walk(start):
            # Enforce depth by pruning traversal.
            depth = _depth_for_dir(cur_dir)
            if depth >= max_depth:
                dirnames[:] = []

            dirnames[:] = [d for d in dirnames if d != ".git"]
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            dirnames.sort()
            filenames.sort()

            if include_dirs:
                for d in dirnames:
                    rp = os.path.relpath(os.path.join(cur_dir, d), root)
                    if not include_hidden and os.path.basename(rp).startswith("."):
                        continue
                    if skipped < cursor:
                        skipped += 1
                        continue
                    if yielded >= max_files:
                        truncated = True
                        next_cursor = cursor + yielded
                        break
                    out.append(rp)
                    yielded += 1
                if truncated:
                    break

            for f in filenames:
                if not include_hidden and f.startswith("."):
                    continue
                rp = os.path.relpath(os.path.join(cur_dir, f), root)
                if skipped < cursor:
                    skipped += 1
                    continue
                if yielded >= max_files:
                    truncated = True
                    next_cursor = cursor + yielded
                    break
                out.append(rp)
                yielded += 1
            if truncated:
                break

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path if path else "",
            "files": out,
            "truncated": bool(truncated),
            "cursor": int(cursor),
            "next_cursor": next_cursor,
            "max_files": max_files,
            "max_depth": max_depth,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="list_workspace_files")


@mcp_tool(write_action=False)
async def find_workspace_paths(
    full_name: str | None = None,
    ref: str = "main",
    path: str = "",
    *,
    pattern: str = "",
    pattern_type: str = "glob",
    include_files: bool = True,
    include_dirs: bool = True,
    include_hidden: bool = True,
    max_results: int = 500,
    max_depth: int = 25,
    cursor: int = 0,
    include_metadata: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Find paths in the workspace by matching names.

    `pattern_type`:
      - "glob" (default): fnmatch-style glob applied to the basename.
      - "regex": Python regex applied to the repo-relative path.
      - "substring": simple substring match applied to the repo-relative path.

    Returns paths in a stable lexicographic traversal order and supports offset
    pagination via `cursor`.
    """

    try:
        import fnmatch

        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        if not isinstance(pattern, str) or not pattern:
            raise ValueError("pattern must be a non-empty string")
        if pattern_type not in {"glob", "regex", "substring"}:
            raise ValueError("pattern_type must be glob/regex/substring")
        if not isinstance(max_results, int) or max_results < 1:
            raise ValueError("max_results must be an int >= 1")
        if not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be an int >= 0")
        if not isinstance(cursor, int) or cursor < 0:
            raise ValueError("cursor must be an int >= 0")

        root = os.path.realpath(repo_dir)
        normalized_path, start = _resolve_workspace_start(repo_dir, path)
        if os.path.isfile(start):
            start = os.path.dirname(start)

        rex = None
        needle = None
        if pattern_type == "regex":
            rex = re.compile(pattern)
        elif pattern_type == "substring":
            needle = pattern

        def _depth_for_dir(cur_dir: str) -> int:
            rel = os.path.relpath(cur_dir, start)
            if rel in {".", ""}:
                return 0
            return rel.count(os.sep) + 1

        def _match(rel_path: str) -> bool:
            if pattern_type == "glob":
                return fnmatch.fnmatch(os.path.basename(rel_path), pattern)
            if rex is not None:
                return rex.search(rel_path) is not None
            return needle in rel_path

        results: list[Any] = []
        scanned = 0
        skipped = 0
        truncated = False
        next_cursor: int | None = None

        for cur_dir, dirnames, filenames in os.walk(start):
            depth = _depth_for_dir(cur_dir)
            if depth >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d != ".git"]
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            dirnames.sort()
            filenames.sort()

            if include_dirs:
                for d in dirnames:
                    rp = os.path.relpath(os.path.join(cur_dir, d), root).replace(
                        "\\", "/"
                    )
                    if not include_hidden and os.path.basename(rp).startswith("."):
                        continue
                    scanned += 1
                    if not _match(rp):
                        continue
                    if skipped < cursor:
                        skipped += 1
                        continue
                    if len(results) >= max_results:
                        truncated = True
                        next_cursor = cursor + len(results)
                        break
                    if include_metadata:
                        abs_path = os.path.join(root, rp)
                        st = os.stat(abs_path)
                        results.append(
                            {"path": rp, "type": "dir", "size_bytes": int(st.st_size)}
                        )
                    else:
                        results.append(rp)
                if truncated:
                    break

            if include_files:
                for f in filenames:
                    if not include_hidden and f.startswith("."):
                        continue
                    rp = os.path.relpath(os.path.join(cur_dir, f), root).replace(
                        "\\", "/"
                    )
                    scanned += 1
                    if not _match(rp):
                        continue
                    if skipped < cursor:
                        skipped += 1
                        continue
                    if len(results) >= max_results:
                        truncated = True
                        next_cursor = cursor + len(results)
                        break
                    if include_metadata:
                        abs_path = os.path.join(root, rp)
                        st = os.stat(abs_path)
                        results.append(
                            {"path": rp, "type": "file", "size_bytes": int(st.st_size)}
                        )
                    else:
                        results.append(rp)
                if truncated:
                    break

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path if path else "",
            "pattern": pattern,
            "pattern_type": pattern_type,
            "cursor": int(cursor),
            "next_cursor": next_cursor,
            "max_results": int(max_results),
            "max_depth": int(max_depth),
            "include_files": bool(include_files),
            "include_dirs": bool(include_dirs),
            "include_metadata": bool(include_metadata),
            "results": results,
            "truncated": bool(truncated),
            "scanned": int(scanned),
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="find_workspace_paths")


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
    include_hidden: bool = True,
    cursor: int = 0,
    *,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Search text files in the repo mirror (workspace clone) (bounded, no shell).

    Searches are always case-insensitive.

    Behavior for `query`:
    - When regex=true, `query` is treated as a Python regular expression.
    - Otherwise `query` is treated as a literal substring match.
    - max_results is enforced as an output limit and supports offset pagination
      via `cursor` (cursor is the offset in the global match stream).
    - max_file_bytes is enforced as a per-file safety limit.
    """

    if not isinstance(query, str) or not query:
        raise ValueError("query must be a non-empty string")

    try:
        # Searches are always case-insensitive; ignore case_sensitive input.
        case_sensitive = False

        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        if max_results is None:
            max_results = 200
        if not isinstance(max_results, int) or max_results < 1:
            raise ValueError("max_results must be an int >= 1")
        if not isinstance(cursor, int) or cursor < 0:
            raise ValueError("cursor must be an int >= 0")

        root = os.path.realpath(repo_dir)
        normalized_path, start = _resolve_workspace_start(repo_dir, path)

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
                "path": normalized_path if path else "",
                "query": query,
                "case_sensitive": case_sensitive,
                "used_regex": False,
                "results": [],
                "truncated": False,
                "cursor": int(cursor),
                "next_cursor": None,
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
        matches_seen = 0
        truncated = False
        next_cursor: int | None = None
        walk_iter = (
            [(os.path.dirname(start), [], [os.path.basename(start)])]
            if single_file
            else os.walk(start)
        )
        for cur_dir, dirnames, filenames in walk_iter:
            dirnames[:] = [d for d in dirnames if d != ".git"]
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]

            # Keep results deterministic (important for cursor pagination).
            dirnames.sort()
            filenames.sort()

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

                            # Offset pagination across the global match stream.
                            if matches_seen < cursor:
                                matches_seen += 1
                                continue
                            matches_seen += 1

                            results.append(
                                {
                                    "file": rel_path,
                                    "line": i,
                                    "text": line.rstrip("\n"),
                                }
                            )

                            if len(results) >= max_results:
                                truncated = True
                                next_cursor = cursor + len(results)
                                break
                except OSError:
                    files_skipped += 1
                    continue

                if truncated:
                    break

            if truncated:
                break

        # Return after scanning the full walk.
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path if path else "",
            "query": query,
            "case_sensitive": case_sensitive,
            "used_regex": used_regex,
            "results": results,
            "truncated": bool(truncated),
            "cursor": int(cursor),
            "next_cursor": next_cursor,
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "max_results": max_results,
            "max_file_bytes": max_file_bytes,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="search_workspace")


@mcp_tool(write_action=False)
async def scan_workspace_tree(
    full_name: str | None = None,
    ref: str = "main",
    path: str = "",
    *,
    # Back-compat / convenience aliases:
    # - max_files maps to max_entries
    # - max_lines/max_chars map to head_max_lines/head_max_chars
    # - max_bytes maps to hash_max_bytes + line_count_max_bytes
    max_files: int | None = None,
    max_lines: int | None = None,
    max_chars: int | None = None,
    max_bytes: int | None = None,
    include_hidden: bool = True,
    include_dirs: bool = False,
    max_entries: int = 2000,
    max_depth: int = 25,
    cursor: int = 0,
    include_hash: bool = True,
    hash_max_bytes: int = 200_000,
    include_line_count: bool = True,
    line_count_max_bytes: int = 200_000,
    include_head: bool = False,
    head_max_lines: int = 20,
    head_max_chars: int = 10_000,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Scan the workspace tree and return bounded metadata for files."""

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        # Normalize alias args.
        # Note: We intentionally keep the canonical parameter names in the
        # response payload (max_entries/head_max_lines/head_max_chars/etc.).
        if max_files is not None:
            max_entries = max_files
        if max_lines is not None:
            head_max_lines = max_lines
            include_head = True
        if max_chars is not None:
            head_max_chars = max_chars
            include_head = True
        if max_bytes is not None:
            hash_max_bytes = max_bytes
            line_count_max_bytes = max_bytes

        if not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be an int >= 1")
        if not isinstance(max_depth, int) or max_depth < 0:
            raise ValueError("max_depth must be an int >= 0")
        if not isinstance(cursor, int) or cursor < 0:
            raise ValueError("cursor must be an int >= 0")
        if not isinstance(hash_max_bytes, int) or hash_max_bytes < 1:
            raise ValueError("hash_max_bytes must be an int >= 1")
        if not isinstance(line_count_max_bytes, int) or line_count_max_bytes < 1:
            raise ValueError("line_count_max_bytes must be an int >= 1")
        if not isinstance(head_max_lines, int) or head_max_lines < 1:
            raise ValueError("head_max_lines must be an int >= 1")
        if not isinstance(head_max_chars, int) or head_max_chars < 1:
            raise ValueError("head_max_chars must be an int >= 1")

        root = os.path.realpath(repo_dir)
        normalized_path, start = _resolve_workspace_start(repo_dir, path)
        if os.path.isfile(start):
            start = os.path.dirname(start)

        def _depth_for_dir(cur_dir: str) -> int:
            rel = os.path.relpath(cur_dir, start)
            if rel in {".", ""}:
                return 0
            return rel.count(os.sep) + 1

        results: list[dict[str, Any]] = []
        skipped = 0
        yielded = 0
        truncated = False
        next_cursor: int | None = None

        for cur_dir, dirnames, filenames in os.walk(start):
            if _depth_for_dir(cur_dir) >= max_depth:
                dirnames[:] = []
            dirnames[:] = [d for d in dirnames if d != ".git"]
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            dirnames.sort()
            filenames.sort()

            if include_dirs:
                for d in dirnames:
                    rp = os.path.relpath(os.path.join(cur_dir, d), root).replace(
                        "\\", "/"
                    )
                    if not include_hidden and os.path.basename(rp).startswith("."):
                        continue
                    if skipped < cursor:
                        skipped += 1
                        continue
                    if yielded >= max_entries:
                        truncated = True
                        next_cursor = cursor + yielded
                        break
                    abs_p = os.path.join(root, rp)
                    try:
                        st = os.stat(abs_p)
                        results.append(
                            {"path": rp, "type": "dir", "size_bytes": int(st.st_size)}
                        )
                    except Exception:
                        results.append({"path": rp, "type": "dir", "size_bytes": None})
                    yielded += 1
                if truncated:
                    break

            for fname in filenames:
                if not include_hidden and fname.startswith("."):
                    continue
                rp = os.path.relpath(os.path.join(cur_dir, fname), root).replace(
                    "\\", "/"
                )
                if skipped < cursor:
                    skipped += 1
                    continue
                if yielded >= max_entries:
                    truncated = True
                    next_cursor = cursor + yielded
                    break
                abs_p = os.path.join(root, rp)
                try:
                    st = os.stat(abs_p)
                except OSError:
                    results.append({"path": rp, "type": "file", "error": "stat_failed"})
                    yielded += 1
                    continue
                is_bin = _is_probably_binary(abs_p)
                entry: dict[str, Any] = {
                    "path": rp,
                    "type": "file",
                    "size_bytes": int(st.st_size),
                    "is_binary": bool(is_bin),
                }
                if include_hash:
                    sha, sha_trunc = _sha256_limited(
                        abs_p, max_bytes=int(hash_max_bytes)
                    )
                    entry["sha256"] = sha
                    entry["sha256_truncated"] = bool(sha_trunc)
                if include_line_count and (not is_bin):
                    lc, lc_trunc = _count_lines_limited(
                        abs_p, max_bytes=int(line_count_max_bytes)
                    )
                    entry["line_count"] = lc
                    entry["line_count_truncated"] = bool(lc_trunc)
                if include_head and (not is_bin):
                    head, head_trunc = _read_first_lines(
                        abs_p,
                        max_lines=int(head_max_lines),
                        max_chars=int(head_max_chars),
                    )
                    entry["head"] = {
                        "lines": head,
                        "truncated": bool(head_trunc),
                        "max_lines": int(head_max_lines),
                        "max_chars": int(head_max_chars),
                    }
                results.append(entry)
                yielded += 1
            if truncated:
                break

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": normalized_path if path else "",
            "cursor": int(cursor),
            "next_cursor": next_cursor,
            "max_entries": int(max_entries),
            "max_depth": int(max_depth),
            "include_hidden": bool(include_hidden),
            "include_dirs": bool(include_dirs),
            "include_hash": bool(include_hash),
            "hash_max_bytes": int(hash_max_bytes),
            "include_line_count": bool(include_line_count),
            "line_count_max_bytes": int(line_count_max_bytes),
            "include_head": bool(include_head),
            "head_max_lines": int(head_max_lines),
            "head_max_chars": int(head_max_chars),
            "results": results,
            "truncated": bool(truncated),
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="scan_workspace_tree")
