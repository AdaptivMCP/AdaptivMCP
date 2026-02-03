"""Fast repo search helpers (ripgrep-backed) with safe fallbacks.

Why this exists
--------------
The workspace mirror can contain very large repositories and very large files.
The pure-Python search tools are correct but can be slow for big repos.

These tools:
  - Use `rg` (ripgrep) when available for speed.
  - Fall back to a streaming Python walker when rg is not installed.
  - Always return line numbers, and optionally a structured excerpt around each
    match using the same large-file-safe reader used elsewhere.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess  # nosec B404
from typing import Any

from github_mcp.server import _structured_tool_error, mcp_tool

from ._shared import _tw
from .fs import _is_probably_binary, _read_lines_excerpt, _workspace_safe_join


_RG_AVAILABLE: bool | None = None


# Default exclusions for ripgrep-backed tools.
#
# Rationale:
# - The workspace mirror can contain a persistent virtualenv (.venv-mcp) which is
#   large/noisy and almost never what callers want to search.
# - Keep defaults conservative and easy to override by explicitly passing
#   exclude_paths/exclude_glob.
_DEFAULT_EXCLUDE_PATHS: list[str] = [".venv-mcp"]


def _apply_default_excludes(
    *,
    exclude_paths: str | list[str] | None,
    exclude_glob: str | list[str] | None,
    normalized_exclude_paths: list[str],
) -> list[str]:
    """Apply default exclude paths only when the caller didn't specify any.

    If callers pass exclude_paths/exclude_glob explicitly (even as an empty list),
    we respect that and do not inject defaults.
    """

    if exclude_paths is None and exclude_glob is None:
        # Prepend defaults so user-specified includes later (if any) can still
        # add additional excludes.
        out = [*_DEFAULT_EXCLUDE_PATHS, *normalized_exclude_paths]
        # De-dupe while preserving order.
        seen: set[str] = set()
        uniq: list[str] = []
        for p in out:
            if p in seen:
                continue
            seen.add(p)
            uniq.append(p)
        return uniq
    return normalized_exclude_paths


def _rg_available() -> bool:
    global _RG_AVAILABLE
    if _RG_AVAILABLE is not None:
        return _RG_AVAILABLE

    path = shutil.which("rg")
    if not path:
        _RG_AVAILABLE = False
        return _RG_AVAILABLE
    try:
        _RG_AVAILABLE = os.access(path, os.X_OK)
    except Exception:
        _RG_AVAILABLE = False
    return _RG_AVAILABLE


def _safe_communicate(
    proc: subprocess.Popen, *, timeout: float = 5.0
) -> tuple[str, str]:
    """Best-effort communicate that never leaves a child process running.

    Some environments (or unexpected child process states) can cause
    `proc.communicate()` to block for longer than we want. When a timeout
    happens, we kill the process and try again to ensure the child is reaped.
    """

    try:
        out, err = proc.communicate(timeout=timeout)
        return out or "", err or ""
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:  # nosec B110
            pass
        try:
            out, err = proc.communicate(timeout=timeout)
            return out or "", err or ""
        except Exception:
            # Final fallback: best-effort drain without a timeout.
            try:
                out, err = proc.communicate()
                return out or "", err or ""
            except Exception:
                return "", ""


def _normalize_globs(glob: str | list[str] | None) -> list[str]:
    if glob is None:
        return []
    if isinstance(glob, str):
        g = glob.strip()
        return [g] if g else []
    if isinstance(glob, list):
        out: list[str] = []
        for item in glob:
            if not isinstance(item, str):
                continue
            s = item.strip()
            if s:
                out.append(s)
        return out
    raise TypeError("glob must be a string, list of strings, or null")


def _normalize_paths(value: str | list[str] | None) -> list[str]:
    """Normalize repo-relative paths/prefixes.

    Notes:
    - Returns POSIX-ish paths ("/" separators).
    - Strips leading "/" so callers can pass either "tests" or "/tests".
    - Keeps empty result for invalid/blank inputs.
    """

    if value is None:
        return []
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return []
        return [s.lstrip("/").replace("\\", "/")]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            s = item.strip()
            if not s:
                continue
            out.append(s.lstrip("/").replace("\\", "/"))
        return out
    raise TypeError("paths must be a string, list of strings, or null")


def _passes_globs(rel_path: str, globs: list[str]) -> bool:
    if not globs:
        return True
    # Match against POSIX-ish paths.
    p = rel_path.replace("\\", "/")
    return any(fnmatch.fnmatch(p, g) for g in globs)


def _passes_path_prefixes(rel_path: str, prefixes: list[str]) -> bool:
    if not prefixes:
        return True
    p = rel_path.replace("\\", "/")
    for raw in prefixes:
        pref = (raw or "").strip().lstrip("/")
        if not pref:
            continue
        pref = pref.replace("\\", "/")
        if p == pref:
            return True
        # Treat as a directory prefix.
        if not pref.endswith("/"):
            pref = pref + "/"
        if p.startswith(pref):
            return True
    return False


def _passes_filters(
    rel_path: str,
    *,
    include_globs: list[str],
    exclude_globs: list[str],
    include_paths: list[str],
    exclude_paths: list[str],
) -> bool:
    # Include filters (tighten search space).
    if include_paths and (not _passes_path_prefixes(rel_path, include_paths)):
        return False
    if include_globs and (not _passes_globs(rel_path, include_globs)):
        return False

    # Exclude filters.
    if exclude_paths and _passes_path_prefixes(rel_path, exclude_paths):
        return False
    if exclude_globs and any(
        fnmatch.fnmatch(rel_path.replace("\\", "/"), g) for g in exclude_globs
    ):
        return False

    return True


def _exclude_globs_from_paths(exclude_paths: list[str]) -> list[str]:
    """Translate excluded paths/prefixes into glob patterns.

    This helps apply the same semantics when delegating to ripgrep.
    """

    out: list[str] = []
    for p in exclude_paths:
        s = (p or "").strip().lstrip("/").replace("\\", "/")
        if not s:
            continue
        if s.endswith("/"):
            out.append(f"{s}**")
            continue
        out.append(s)
        out.append(f"{s}/**")
    return out


def _python_walk_files(
    repo_dir: str,
    base_rel: str,
    *,
    include_hidden: bool,
    globs: list[str],
    exclude_globs: list[str],
    include_paths: list[str],
    exclude_paths: list[str],
    max_results: int,
) -> list[str]:
    base_abs = _workspace_safe_join(repo_dir, base_rel or ".")
    base_abs = os.path.realpath(base_abs)

    out: list[str] = []
    for root, dirs, files in os.walk(base_abs):
        # Skip .git and optionally hidden directories.
        rel_root = os.path.relpath(root, repo_dir).replace("\\", "/")
        if rel_root == ".git" or rel_root.startswith(".git/"):
            dirs[:] = []
            continue
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]

        for f in files:
            if not include_hidden and f.startswith("."):
                continue
            abs_path = os.path.join(root, f)
            try:
                rel_path = os.path.relpath(abs_path, repo_dir).replace("\\", "/")
            except Exception:  # nosec B112
                continue
            if rel_path == "." or rel_path.startswith(".."):
                continue
            if not _passes_filters(
                rel_path,
                include_globs=globs,
                exclude_globs=exclude_globs,
                include_paths=include_paths,
                exclude_paths=exclude_paths,
            ):
                continue
            out.append(rel_path)
            if len(out) >= max_results:
                return out
    return out


def _python_search(
    repo_dir: str,
    base_rel: str,
    query: str,
    *,
    regex: bool,
    case_sensitive: bool,
    include_hidden: bool,
    globs: list[str],
    exclude_globs: list[str],
    include_paths: list[str],
    exclude_paths: list[str],
    max_results: int,
    max_file_bytes: int | None,
) -> tuple[list[dict[str, Any]], bool]:
    if not isinstance(query, str):
        query = "" if query is None else str(query)
    if not query:
        return ([], False)
    if not isinstance(max_results, int) or max_results < 1:
        max_results = 200

    flags = 0 if case_sensitive else re.IGNORECASE
    pattern = None
    if regex:
        try:
            pattern = re.compile(query, flags)
        except re.error:
            pattern = None
            regex = False
    needle = query if case_sensitive else query.lower()

    matches: list[dict[str, Any]] = []
    truncated = False

    for rel_path in _python_walk_files(
        repo_dir,
        base_rel,
        include_hidden=include_hidden,
        globs=globs,
        exclude_globs=exclude_globs,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
        max_results=50_000,
    ):
        try:
            abs_path = _workspace_safe_join(repo_dir, rel_path)
            if os.path.isdir(abs_path):
                continue
            if (
                max_file_bytes is not None
                and os.path.getsize(abs_path) > max_file_bytes
            ):
                continue
            if _is_probably_binary(abs_path):
                continue
        except Exception:  # nosec B112
            continue

        try:
            with open(abs_path, encoding="utf-8", errors="replace") as f:
                for line_no, raw in enumerate(f, start=1):
                    line = raw.rstrip("\n")
                    if pattern is not None:
                        m = pattern.search(line)
                        if not m:
                            continue
                        col = int(m.start()) + 1
                    else:
                        hay = line if case_sensitive else line.lower()
                        idx = hay.find(needle)
                        if idx == -1:
                            continue
                        col = int(idx) + 1

                    matches.append(
                        {
                            "path": rel_path,
                            "line": int(line_no),
                            "column": int(col),
                            "text": line,
                        }
                    )
                    if len(matches) >= max_results:
                        truncated = True
                        return matches, truncated
        except Exception:  # nosec B112
            continue

    return matches, truncated


def _parse_max_file_bytes(value: int | str | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        raise TypeError("max_file_bytes must be an int, string, or null")
    s = value.strip()
    if not s:
        return None
    # Accept common suffixes.
    m = re.fullmatch(r"(\d+)([KMG]?)", s, flags=re.IGNORECASE)
    if not m:
        raise ValueError("max_file_bytes must look like 123, 10K, 5M, 1G")
    n = int(m.group(1))
    suf = (m.group(2) or "").upper()
    mult = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3}[suf]
    return n * mult


@mcp_tool(write_action=False)
async def rg_list_workspace_files(
    full_name: str,
    ref: str = "main",
    path: str = "",
    *,
    include_hidden: bool = False,
    glob: str | list[str] | None = None,
    exclude_glob: str | list[str] | None = None,
    include_paths: str | list[str] | None = None,
    exclude_paths: str | list[str] | None = None,
    max_results: int = 5000,
) -> dict[str, Any]:
    """List files quickly (ripgrep `--files`) with an os.walk fallback."""

    try:
        if not isinstance(max_results, int) or max_results < 1:
            raise ValueError("max_results must be an int >= 1")

        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        base_rel = (path or "").strip().lstrip("/")
        globs = _normalize_globs(glob)
        excl_globs = _normalize_globs(exclude_glob)
        incl_paths = _normalize_paths(include_paths)
        excl_paths = _normalize_paths(exclude_paths)
        excl_paths = _apply_default_excludes(
            exclude_paths=exclude_paths,
            exclude_glob=exclude_glob,
            normalized_exclude_paths=excl_paths,
        )
        # Ensure exclude_paths are also applied to rg via glob patterns.
        excl_globs = [*excl_globs, *_exclude_globs_from_paths(excl_paths)]
        base_rel_effective = "" if incl_paths else base_rel

        files: list[str] = []
        truncated = False
        engine = "python"

        if _rg_available():
            engine = "rg"
            cmd = ["rg", "--files"]
            if include_hidden:
                cmd.append("--hidden")
            for g in globs:
                cmd.extend(["--glob", g])
            for g in excl_globs:
                # rg treats negated globs as exclusions.
                cmd.extend(["--glob", f"!{g}"])

            # If include_paths is provided, search only those targets from repo root.
            if incl_paths:
                for p in incl_paths:
                    joined = os.path.normpath(p).replace("\\", "/")
                    if joined.startswith("../") or joined == "..":
                        continue
                    cmd.append(joined)
                base_abs = repo_dir
            else:
                base_abs = _workspace_safe_join(repo_dir, base_rel_effective or ".")
            proc = subprocess.run(  # nosec B603
                cmd, cwd=base_abs, capture_output=True, text=True, timeout=30
            )
            if proc.returncode not in (0, 1):
                raise RuntimeError((proc.stderr or proc.stdout or "rg failed").strip())
            for line in (proc.stdout or "").splitlines():
                if not line:
                    continue
                # rg emits paths relative to cwd; normalize to repo root.
                rel = os.path.normpath(os.path.join(base_rel_effective, line)).replace(
                    "\\", "/"
                )
                if not _passes_filters(
                    rel,
                    include_globs=globs,
                    exclude_globs=excl_globs,
                    include_paths=incl_paths,
                    exclude_paths=excl_paths,
                ):
                    continue
                files.append(rel)
                if len(files) >= max_results:
                    truncated = True
                    break
        else:
            files = _python_walk_files(
                repo_dir,
                base_rel_effective,
                include_hidden=bool(include_hidden),
                globs=globs,
                exclude_globs=excl_globs,
                include_paths=incl_paths,
                exclude_paths=excl_paths,
                max_results=int(max_results),
            )
            truncated = len(files) >= max_results

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "status": "ok",
            "ok": True,
            "engine": engine,
            "path": (path or "").strip().lstrip("/"),
            "include_hidden": bool(include_hidden),
            "glob": globs,
            "exclude_glob": excl_globs,
            "include_paths": incl_paths,
            "exclude_paths": excl_paths,
            "files": files,
            "truncated": bool(truncated),
            "max_results": int(max_results),
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="rg_list_workspace_files")


@mcp_tool(write_action=False)
async def rg_search_workspace(
    full_name: str,
    ref: str = "main",
    query: str = "",
    path: str = "",
    *,
    regex: bool = False,
    case_sensitive: bool = True,
    include_hidden: bool = False,
    glob: str | list[str] | None = None,
    exclude_glob: str | list[str] | None = None,
    include_paths: str | list[str] | None = None,
    exclude_paths: str | list[str] | None = None,
    max_results: int = 200,
    context_lines: int = 0,
    max_file_bytes: int | str | None = None,
) -> dict[str, Any]:
    """Search repository content and return match line numbers.

    Returns structured matches with {path, line, column, text}. When
    context_lines > 0, each match includes an `excerpt` object with surrounding
    lines and line numbers.

    Searches are always case-insensitive.
    """

    try:
        # Searches are always case-insensitive; ignore case_sensitive input.
        case_sensitive = False

        if not isinstance(query, str):
            query = "" if query is None else str(query)
        query = query.strip()
        if not isinstance(max_results, int) or max_results < 1:
            max_results = 200
        if not isinstance(context_lines, int) or context_lines < 0:
            context_lines = 0

        max_bytes = _parse_max_file_bytes(max_file_bytes)

        base_rel = (path or "").strip().lstrip("/")
        globs = _normalize_globs(glob)
        excl_globs = _normalize_globs(exclude_glob)
        incl_paths = _normalize_paths(include_paths)
        excl_paths = _normalize_paths(exclude_paths)
        excl_paths = _apply_default_excludes(
            exclude_paths=exclude_paths,
            exclude_glob=exclude_glob,
            normalized_exclude_paths=excl_paths,
        )
        excl_globs = [*excl_globs, *_exclude_globs_from_paths(excl_paths)]
        base_rel_effective = "" if incl_paths else base_rel

        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        if not query:
            return {
                "full_name": full_name,
                "ref": effective_ref,
                "status": "ok",
                "ok": True,
                "engine": "python",
                "query": query,
                "path": base_rel,
                "regex": bool(regex),
                "case_sensitive": bool(case_sensitive),
                "include_hidden": bool(include_hidden),
                "glob": globs,
                "exclude_glob": excl_globs,
                "include_paths": incl_paths,
                "exclude_paths": excl_paths,
                "max_results": int(max_results),
                "context_lines": int(context_lines),
                "max_file_bytes": max_bytes,
                "matches": [],
                "truncated": False,
            }

        deps = _tw()._workspace_deps()
        repo_dir = await deps["clone_repo"](
            full_name, ref=effective_ref, preserve_changes=True
        )

        # When include_paths is provided, we run from repo root and pass explicit
        # targets to ripgrep. Otherwise we use `path` as the working directory.
        base_abs = (
            repo_dir
            if incl_paths
            else _workspace_safe_join(repo_dir, base_rel_effective or ".")
        )

        matches: list[dict[str, Any]] = []
        truncated = False
        engine = "python"

        if _rg_available():
            try:
                engine = "rg"
                cmd = ["rg", "--json", "--line-number", "--column"]
                if not regex:
                    cmd.append("-F")
                if not case_sensitive:
                    cmd.append("-i")
                if include_hidden:
                    cmd.append("--hidden")
                if max_bytes is not None:
                    # rg accepts bytes when passed as an integer string.
                    cmd.extend(["--max-filesize", str(int(max_bytes))])
                for g in globs:
                    cmd.extend(["--glob", g])
                for g in excl_globs:
                    cmd.extend(["--glob", f"!{g}"])
                cmd.append("--")
                cmd.append(query)

                if incl_paths:
                    for p in incl_paths:
                        joined = os.path.normpath(p).replace("\\", "/")
                        if joined.startswith("../") or joined == "..":
                            continue
                        cmd.append(joined)

                proc = subprocess.Popen(  # nosec B603
                    cmd,
                    cwd=base_abs,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                assert proc.stdout is not None  # nosec B101
                try:
                    for raw in proc.stdout:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            evt = json.loads(raw)
                        except Exception:  # nosec B112
                            continue
                        if evt.get("type") != "match":
                            continue
                        data = evt.get("data") or {}
                        rel = data.get("path", {}).get("text")
                        if not isinstance(rel, str) or not rel:
                            continue
                        # Normalize to repo-root relative path.
                        rel_norm = os.path.normpath(
                            os.path.join(base_rel_effective, rel)
                        ).replace("\\", "/")
                        if not _passes_filters(
                            rel_norm,
                            include_globs=globs,
                            exclude_globs=excl_globs,
                            include_paths=incl_paths,
                            exclude_paths=excl_paths,
                        ):
                            continue
                        line_no = int(data.get("line_number") or 0)
                        sub = data.get("submatches") or []
                        col = 1
                        if sub and isinstance(sub, list) and isinstance(sub[0], dict):
                            try:
                                col = int(sub[0].get("start", 0)) + 1
                            except Exception:
                                col = 1
                        text_line = (data.get("lines", {}) or {}).get("text")
                        if not isinstance(text_line, str):
                            text_line = ""
                        text_line = text_line.rstrip("\n")
                        matches.append(
                            {
                                "path": rel_norm,
                                "line": int(line_no),
                                "column": int(col),
                                "text": text_line,
                            }
                        )
                        if len(matches) >= max_results:
                            truncated = True
                            break
                finally:
                    try:
                        if truncated and proc.poll() is None:
                            proc.kill()
                    except Exception:  # nosec B110
                        pass
                    _safe_communicate(proc, timeout=5)

                # rg returns 1 when no matches.
                if proc.returncode not in (0, 1, None):
                    stderr = ""
                    try:
                        stderr = proc.stderr.read() if proc.stderr else ""
                    except Exception:
                        stderr = ""
                    raise RuntimeError((stderr or "rg failed").strip())

            except Exception:
                # If rg is present but fails to execute (PATH issues, permission,
                # incompatible binary, etc.), fall back to Python so the tool
                # never hard-fails or wedges on a stuck subprocess.
                matches, truncated = _python_search(
                    repo_dir,
                    base_rel_effective,
                    query.strip(),
                    regex=bool(regex),
                    case_sensitive=bool(case_sensitive),
                    include_hidden=bool(include_hidden),
                    globs=globs,
                    exclude_globs=excl_globs,
                    include_paths=incl_paths,
                    exclude_paths=excl_paths,
                    max_results=int(max_results),
                    max_file_bytes=max_bytes,
                )
                engine = "python"

        else:
            matches, truncated = _python_search(
                repo_dir,
                base_rel_effective,
                query.strip(),
                regex=bool(regex),
                case_sensitive=bool(case_sensitive),
                include_hidden=bool(include_hidden),
                globs=globs,
                exclude_globs=excl_globs,
                include_paths=incl_paths,
                exclude_paths=excl_paths,
                max_results=int(max_results),
                max_file_bytes=max_bytes,
            )

        if context_lines > 0 and matches:
            for m in matches:
                try:
                    rel_path = m.get("path")
                    line_no = int(m.get("line") or 1)
                    abs_path = _workspace_safe_join(repo_dir, str(rel_path))
                    start = max(1, line_no - int(context_lines))
                    excerpt = _read_lines_excerpt(
                        abs_path,
                        start_line=int(start),
                        max_lines=int(context_lines) * 2 + 1,
                        max_chars=2000000,
                    )
                    m["excerpt"] = excerpt
                except Exception:  # nosec B110
                    # Best-effort; omit excerpt if anything fails.
                    pass

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "status": "ok",
            "ok": True,
            "engine": engine,
            "query": query,
            "path": base_rel,
            "regex": bool(regex),
            "case_sensitive": bool(case_sensitive),
            "include_hidden": bool(include_hidden),
            "glob": globs,
            "exclude_glob": excl_globs,
            "include_paths": incl_paths,
            "exclude_paths": excl_paths,
            "max_results": int(max_results),
            "context_lines": int(context_lines),
            "max_file_bytes": max_bytes,
            "matches": matches,
            "truncated": bool(truncated),
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="rg_search_workspace")
