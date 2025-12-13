"""Workspace and command tools for GitHub MCP."""

import os
import shlex
import sys
import difflib
import re
from typing import Any, Dict, List, Optional

from github_mcp.config import RUN_COMMAND_MAX_CHARS
from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    CONTROLLER_REPO,
    _ensure_write_allowed,
    _structured_tool_error,
    mcp_tool,
)
from github_mcp.utils import _effective_ref_for_repo
from github_mcp.workspace import (
    _apply_patch_to_repo,
    _clone_repo,
    _prepare_temp_virtualenv,
    _run_shell,
    _workspace_path,
)

# ------------------------------------------------------------------------------
# Workspace / full-environment tools
# ------------------------------------------------------------------------------


def _workspace_deps() -> Dict[str, Any]:
    main_module = sys.modules.get("main")
    return {
        "clone_repo": getattr(main_module, "_clone_repo", _clone_repo),
        "run_shell": getattr(main_module, "_run_shell", _run_shell),
        "prepare_temp_virtualenv": getattr(
            main_module, "_prepare_temp_virtualenv", _prepare_temp_virtualenv
        ),
        "apply_patch_to_repo": getattr(main_module, "_apply_patch_to_repo", _apply_patch_to_repo),
        "ensure_write_allowed": getattr(
            main_module, "_ensure_write_allowed", _ensure_write_allowed
        ),
    }

def _resolve_full_name(
    full_name: Optional[str], *, owner: Optional[str] = None, repo: Optional[str] = None
) -> str:
    if isinstance(full_name, str) and full_name.strip():
        return full_name.strip()
    if isinstance(owner, str) and owner.strip() and isinstance(repo, str) and repo.strip():
        return f"{owner.strip()}/{repo.strip()}"
    return CONTROLLER_REPO


def _resolve_ref(ref: str, *, branch: Optional[str] = None) -> str:
    if isinstance(branch, str) and branch.strip():
        return branch.strip()
    return ref


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
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        workspace_dir = _workspace_path(full_name, effective_ref)
        existed = os.path.isdir(os.path.join(workspace_dir, ".git"))

        deps = _workspace_deps()
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


@mcp_tool(write_action=True)
async def apply_patch_to_workspace(
    full_name: Optional[str] = None,
    ref: str = "main",
    patch: str = "",
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a unified diff to the persistent workspace clone.

    This provides a structured alternative to relying on ad-hoc shell helpers
    like `apply_patch`.
    """

    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("patch must be a non-empty unified diff string")

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)

        deps["ensure_write_allowed"](
            f"apply_patch_to_workspace for {full_name}@{effective_ref}",
        )

        repo_dir = await deps["clone_repo"](
            full_name,
            ref=effective_ref,
            preserve_changes=True,
        )
        await deps["apply_patch_to_repo"](repo_dir, patch)

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "status": "applied",
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="apply_patch_to_workspace")


# ------------------------------------------------------------------------------
# Workspace file helpers and diff builders
# ------------------------------------------------------------------------------


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


def _workspace_build_unified_diff(
    original: str,
    updated: str,
    *,
    path: str,
    context_lines: int,
) -> str:
    if context_lines < 0:
        raise ValueError("context_lines must be >= 0")

    original_lines = original.splitlines(keepends=True)
    updated_lines = updated.splitlines(keepends=True)

    diff_lines = difflib.unified_diff(
        original_lines,
        updated_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context_lines,
    )
    return "".join(diff_lines)


def _workspace_apply_sections(text: str, sections: Optional[List[Dict[str, Any]]]) -> str:
    if not sections:
        raise ValueError("sections must be a non-empty list")

    lines = text.splitlines(keepends=True)
    total = len(lines)

    ordered = sorted(sections, key=lambda s: int(s.get("start_line", 0)))

    out: List[str] = []
    cursor = 1

    for section in ordered:
        try:
            start = int(section["start_line"])
            end = int(section["end_line"])
        except KeyError as exc:
            raise ValueError("each section must have 'start_line' and 'end_line'") from exc

        new_text = section.get("new_text", "")

        if start < 1:
            raise ValueError("start_line must be >= 1")
        if end < start - 1:
            raise ValueError("end_line must be >= start_line - 1")

        if cursor <= start - 1 and total > 0:
            out.extend(lines[cursor - 1 : min(start - 1, total)])

        if new_text:
            out.extend(new_text.splitlines(keepends=True))

        cursor = max(cursor, end + 1)

    if total > 0 and cursor <= total:
        out.extend(lines[cursor - 1 :])

    return "".join(out)



def _normalize_patch_path(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value.lstrip("/\\")


def _extract_patch_file_blocks(patch: str) -> List[Dict[str, str]]:
    """Extract (a_path, b_path) pairs for each file block in a unified diff."""

    patch = patch or ""
    lines = patch.splitlines()

    blocks: List[Dict[str, str]] = []

    # Prefer diff --git headers when present because they establish file boundaries.
    has_diff_git = any(line.startswith("diff --git ") for line in lines)

    if has_diff_git:
        for line in lines:
            if not line.startswith("diff --git "):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            blocks.append(
                {
                    "a": _normalize_patch_path(parts[2]),
                    "b": _normalize_patch_path(parts[3]),
                }
            )
        return blocks

    # Fallback: use ---/+++ headers for diffs that omit diff --git lines.
    a_path = ""
    b_path = ""
    for line in lines:
        if line.startswith("--- "):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                a_path = _normalize_patch_path(parts[1])
        elif line.startswith("+++ "):
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                b_path = _normalize_patch_path(parts[1])

    if a_path or b_path:
        blocks.append({"a": a_path, "b": b_path})

    return blocks


def _extract_touched_paths_from_patch(patch: str) -> List[str]:
    """Extract repository-relative *logical* paths touched by a unified diff.

    Returns one entry per file block. For creates/deletes, this is the non-dev/null
    path. For renames, this is the new (b/) path.
    """

    logical_paths: List[str] = []
    for blk in _extract_patch_file_blocks(patch):
        a_path = (blk.get("a") or "").strip()
        b_path = (blk.get("b") or "").strip()

        a_is_null = a_path in {"dev/null", ""}
        b_is_null = b_path in {"dev/null", ""}

        if not b_is_null:
            logical = b_path
        elif not a_is_null:
            logical = a_path
        else:
            logical = ""

        if logical:
            logical_paths.append(logical)

    # De-dupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for pth in logical_paths:
        if pth in seen:
            continue
        seen.add(pth)
        out.append(pth)
    return out


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
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        info = _workspace_read_text(repo_dir, path)
        info.update({"full_name": full_name, "ref": effective_ref, "repo_dir": repo_dir})
        return info
    except Exception as exc:
        return _structured_tool_error(exc, context="get_workspace_file_contents")


@mcp_tool(write_action=False)
async def build_unified_diff_from_workspace(
    full_name: Optional[str] = None,
    path: str = "",
    updated_content: str = "",
    ref: str = "main",
    context_lines: int = 3,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a unified diff against the current workspace file content."""

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        original = _workspace_read_text(repo_dir, path).get("text", "")
        patch = _workspace_build_unified_diff(
            original,
            updated_content,
            path=path,
            context_lines=context_lines,
        )
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": path,
            "patch": patch,
            "context_lines": context_lines,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="build_unified_diff_from_workspace")


@mcp_tool(write_action=False)
async def build_section_based_diff_from_workspace(
    full_name: Optional[str] = None,
    path: str = "",
    sections: Optional[List[Dict[str, Any]]] = None,
    ref: str = "main",
    context_lines: int = 3,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a unified diff by applying line-based sections to the workspace file."""

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        original = _workspace_read_text(repo_dir, path).get("text", "")
        updated_text = _workspace_apply_sections(original, sections)
        patch = _workspace_build_unified_diff(
            original,
            updated_text,
            path=path,
            context_lines=context_lines,
        )
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": path,
            "patch": patch,
            "context_lines": context_lines,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="build_section_based_diff_from_workspace")


@mcp_tool(write_action=True)
async def apply_patch_to_workspace_file(
    full_name: Optional[str] = None,
    ref: str = "main",
    path: str = "",
    patch: str = "",
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a unified diff that is intended to target a single workspace file.

    This enforces that the diff touches exactly one file and that it matches the
    provided `path`.
    """

    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("patch must be a non-empty unified diff string")

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)

        normalized_target = (path or "").lstrip("/\\")

        # Validate that the patch targets exactly one logical file. For create/delete
        # operations, the logical file is the non-dev/null path. For renames, the
        # logical file is the new (b/) path.
        touched_paths = _extract_touched_paths_from_patch(patch)
        if not touched_paths:
            raise ValueError("patch did not include any file headers to validate")
        if len(touched_paths) != 1:
            raise ValueError(f"patch must touch exactly one file; touched={touched_paths!r}")

        logical_path = touched_paths[0]

        # If the patch is a rename, accept either old or new path (still single-file).
        blocks = _extract_patch_file_blocks(patch)
        allowed = {logical_path}
        if blocks:
            a_path = _normalize_patch_path(blocks[0].get("a") or "")
            b_path = _normalize_patch_path(blocks[0].get("b") or "")
            if a_path and a_path != "dev/null":
                allowed.add(a_path)
            if b_path and b_path != "dev/null":
                allowed.add(b_path)

        if normalized_target not in allowed:
            raise ValueError(
                f"patch path mismatch: expected {normalized_target!r} to match one of {sorted(allowed)!r}"
            )

        deps["ensure_write_allowed"](
            f"apply_patch_to_workspace_file {path} for {full_name}@{effective_ref}",
        )
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        await deps["apply_patch_to_repo"](repo_dir, patch)

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "path": path,
            "touched_paths": touched_paths,
            "logical_path": logical_path,
            "status": "applied",
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="apply_patch_to_workspace_file")



@mcp_tool(write_action=False)
async def list_workspace_files(
    full_name: Optional[str] = None,
    ref: str = "main",
    path: str = "",
    max_files: int = 500,
    max_depth: int = 20,
    include_hidden: bool = False,
    include_dirs: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """List files in the workspace clone (bounded, no shell)."""

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        root = os.path.realpath(repo_dir)
        start = os.path.realpath(os.path.join(repo_dir, path)) if path else root
        if not start.startswith(root):
            raise ValueError("path must stay within repo")

        out: list[str] = []
        truncated = False

        for cur_dir, dirnames, filenames in os.walk(start):
            rel_dir = os.path.relpath(cur_dir, root)
            depth = 0 if rel_dir == os.curdir else rel_dir.count(os.sep) + 1
            if depth > max_depth:
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
                    if len(out) >= max_files:
                        truncated = True
                        break
                if truncated:
                    break

            for f in filenames:
                if not include_hidden and f.startswith("."):
                    continue
                rp = os.path.relpath(os.path.join(cur_dir, f), root)
                out.append(rp)
                if len(out) >= max_files:
                    truncated = True
                    break
            if truncated:
                break

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "path": path,
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
    use_regex: bool = False,
    case_sensitive: bool = False,
    max_results: int = 100,
    max_file_bytes: int = 1_000_000,
    include_hidden: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Search text files in the workspace clone (bounded, no shell)."""

    if not isinstance(query, str) or not query:
        raise ValueError("query must be a non-empty string")

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        root = os.path.realpath(repo_dir)
        start = os.path.realpath(os.path.join(repo_dir, path)) if path else root
        if not start.startswith(root):
            raise ValueError("path must stay within repo")

        flags = 0 if case_sensitive else re.IGNORECASE
        matcher = re.compile(query, flags=flags) if use_regex else None

        results: list[dict[str, Any]] = []
        truncated = False
        files_scanned = 0
        files_skipped = 0

        needle = query if case_sensitive else query.lower()

        for cur_dir, dirnames, filenames in os.walk(start):
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

                if st.st_size > max_file_bytes:
                    files_skipped += 1
                    continue

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
                            if use_regex:
                                if not matcher or not matcher.search(line):
                                    continue
                            else:
                                hay = line if case_sensitive else line.lower()
                                if needle not in hay:
                                    continue

                            results.append(
                                {
                                    "file": rel_path,
                                    "line": i,
                                    "text": line.rstrip("\n")[:400],
                                }
                            )
                            if len(results) >= max_results:
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
            "path": path,
            "query": query,
            "use_regex": use_regex,
            "case_sensitive": case_sensitive,
            "results": results,
            "truncated": truncated,
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "max_results": max_results,
            "max_file_bytes": max_file_bytes,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="search_workspace")


@mcp_tool(write_action=False)
async def run_command(
    full_name: Optional[str] = None,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a shell command inside the repo workspace and return its result.

    Use this for tests, linters, or project scripts that need the real tree and virtualenv. The workspace
    persists across calls so installed dependencies and edits are reused."""

    env: Optional[Dict[str, str]] = None
    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        if len(command) > RUN_COMMAND_MAX_CHARS:
            raise ValueError(
                f"run_command.command is too long ({len(command)} chars); "
                "use diff-based tools (apply_text_update_and_commit, "
                "apply_patch_and_commit, update_file_sections_and_commit) "
                "for large edits instead of embedding scripts in command."
            )
        needs_write_gate = mutating or installing_dependencies or (patch is not None) or not use_temp_venv
        if needs_write_gate:
            deps["ensure_write_allowed"](f"run_command {command} in {full_name}@{effective_ref}")
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        if patch:
            await deps["apply_patch_to_repo"](repo_dir, patch)

        if use_temp_venv:
            env = await deps["prepare_temp_virtualenv"](repo_dir)

        cwd = repo_dir
        if workdir:
            cwd = os.path.join(repo_dir, workdir)

        # Optional dependency installation. If requested, install requirements.txt when present
        # (unless the command already appears to be installing deps).
        install_result = None
        if installing_dependencies and use_temp_venv:
            req_path = os.path.join(repo_dir, "requirements.txt")
            cmd_lower = command.lower()
            already_installing = ("pip install" in cmd_lower) or ("pip3 install" in cmd_lower)
            if (not already_installing) and os.path.exists(req_path):
                install_result = await deps["run_shell"](
                    "python -m pip install -r requirements.txt",
                    cwd=cwd,
                    timeout_seconds=max(600, timeout_seconds),
                    env=env,
                )
                if isinstance(install_result, dict) and install_result.get("exit_code", 0) != 0:
                    stderr = (install_result.get("stderr") or "")
                    stdout = (install_result.get("stdout") or "")
                    raise GitHubAPIError(
                        "Dependency installation failed: " + (stderr.strip() or stdout.strip())
                    )

        result = await deps["run_shell"](
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=env,
        )
        out: Dict[str, Any] = {
            "repo_dir": repo_dir,
            "workdir": workdir,
            "install": install_result,
            "result": result,
        }

        # If a python dependency is missing, nudge the assistant to rerun with deps installation.
        if (
            not installing_dependencies
            and isinstance(result, dict)
            and result.get("exit_code", 0) != 0
        ):
            stderr = (result.get("stderr") or "")
            stdout = (result.get("stdout") or "")
            combined = f"{stderr}\n{stdout}"
            mm = re.search(
                r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]",
                combined,
            )
            if mm:
                out["dependency_hint"] = {
                    "missing_module": mm.group(1),
                    "message": "Missing python dependency. Re-run run_command with installing_dependencies=true.",
                }

        return out
    except Exception as exc:
        return _structured_tool_error(exc, context="run_command")




@mcp_tool(write_action=True)
async def workspace_create_branch(
    full_name: Optional[str] = None,
    base_ref: str = "main",
    new_branch: str = "",
    push: bool = True,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a branch using the workspace (git), optionally pushing to origin.

    This exists because some direct GitHub-API branch-creation calls can be blocked upstream.
    """

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        base_ref = _resolve_ref(base_ref, branch=branch)
        effective_base = _effective_ref_for_repo(full_name, base_ref)

        if not isinstance(new_branch, str) or not new_branch:
            raise ValueError("new_branch must be a non-empty string")

        # Conservative branch-name validation.
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", new_branch):
            raise ValueError("new_branch contains invalid characters")
        if ".." in new_branch or "@{" in new_branch:
            raise ValueError("new_branch contains invalid ref sequence")
        if new_branch.startswith("/") or new_branch.endswith("/"):
            raise ValueError("new_branch must not start or end with '/'")
        if new_branch.endswith(".lock"):
            raise ValueError("new_branch must not end with '.lock'")

        _ensure_write_allowed(
            f"workspace_create_branch {new_branch} from {full_name}@{effective_base}",
            target_ref=effective_base,
        )

        repo_dir = await deps["clone_repo"](full_name, ref=effective_base, preserve_changes=True)

        checkout = await deps["run_shell"](
            f"git checkout -b {shlex.quote(new_branch)}",
            cwd=repo_dir,
            timeout_seconds=120,
        )
        if checkout.get("exit_code", 0) != 0:
            stderr = checkout.get("stderr", "") or checkout.get("stdout", "")
            raise GitHubAPIError(f"git checkout -b failed: {stderr}")

        push_result = None
        if push:
            push_result = await deps["run_shell"](
                f"git push -u origin {shlex.quote(new_branch)}",
                cwd=repo_dir,
                timeout_seconds=300,
            )
            if push_result.get("exit_code", 0) != 0:
                stderr = push_result.get("stderr", "") or push_result.get("stdout", "")
                raise GitHubAPIError(f"git push failed: {stderr}")

        return {
            "repo_dir": repo_dir,
            "base_ref": effective_base,
            "new_branch": new_branch,
            "checkout": checkout,
            "push": push_result,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_create_branch")

@mcp_tool(write_action=True)
async def commit_workspace(
    full_name: Optional[str] = None,
    ref: str = "main",
    message: str = "Commit workspace changes",
    add_all: bool = True,
    push: bool = True,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit workspace changes and optionally push them."""

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        _ensure_write_allowed(
            f"commit_workspace for {full_name}@{effective_ref}",
            target_ref=effective_ref,
        )
        deps = _workspace_deps()
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        if add_all:
            add_result = await deps["run_shell"]("git add -A", cwd=repo_dir, timeout_seconds=120)
            if add_result["exit_code"] != 0:
                stderr = add_result.get("stderr", "") or add_result.get("stdout", "")
                raise GitHubAPIError(f"git add failed: {stderr}")

        status_result = await deps["run_shell"](
            "git status --porcelain", cwd=repo_dir, timeout_seconds=60
        )
        status_lines = status_result.get("stdout", "").strip().splitlines()
        if not status_lines:
            raise GitHubAPIError("No changes to commit in workspace")

        commit_cmd = f"git commit -m {shlex.quote(message)}"
        commit_result = await deps["run_shell"](commit_cmd, cwd=repo_dir, timeout_seconds=300)
        if commit_result["exit_code"] != 0:
            stderr = commit_result.get("stderr", "") or commit_result.get("stdout", "")
            raise GitHubAPIError(f"git commit failed: {stderr}")

        push_result = None
        if push:
            push_cmd = f"git push origin HEAD:{effective_ref}"
            push_result = await deps["run_shell"](push_cmd, cwd=repo_dir, timeout_seconds=300)
            if push_result["exit_code"] != 0:
                stderr = push_result.get("stderr", "") or push_result.get("stdout", "")
                raise GitHubAPIError(f"git push failed: {stderr}")

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "status": status_lines,
            "commit": commit_result,
            "push": push_result,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="commit_workspace")


@mcp_tool(write_action=True)
async def commit_workspace_files(
    full_name: Optional[str],
    files: List[str],
    ref: str = "main",
    message: str = "Commit selected workspace changes",
    push: bool = True,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit and optionally push specific files from the persistent workspace."""

    if not files:
        raise ValueError("files must be a non-empty list of paths")

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)
        _ensure_write_allowed(
            f"commit_workspace_files for {full_name}@{effective_ref}",
            target_ref=effective_ref,
        )
        deps = _workspace_deps()
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        add_cmd = "git add -- " + " ".join(shlex.quote(path) for path in files)
        add_result = await deps["run_shell"](add_cmd, cwd=repo_dir, timeout_seconds=120)
        if add_result["exit_code"] != 0:
            stderr = add_result.get("stderr", "") or add_result.get("stdout", "")
            raise GitHubAPIError(f"git add failed: {stderr}")

        staged_files_result = await deps["run_shell"](
            "git diff --cached --name-only", cwd=repo_dir, timeout_seconds=60
        )
        staged_files = staged_files_result.get("stdout", "").strip().splitlines()
        if not staged_files:
            raise GitHubAPIError("No staged changes to commit for provided files")

        commit_cmd = f"git commit -m {shlex.quote(message)}"
        commit_result = await deps["run_shell"](commit_cmd, cwd=repo_dir, timeout_seconds=300)
        if commit_result["exit_code"] != 0:
            stderr = commit_result.get("stderr", "") or commit_result.get("stdout", "")
            raise GitHubAPIError(f"git commit failed: {stderr}")

        push_result = None
        if push:
            push_cmd = f"git push origin HEAD:{effective_ref}"
            push_result = await deps["run_shell"](push_cmd, cwd=repo_dir, timeout_seconds=300)
            if push_result["exit_code"] != 0:
                stderr = push_result.get("stderr", "") or push_result.get("stdout", "")
                raise GitHubAPIError(f"git push failed: {stderr}")

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "staged_files": staged_files,
            "commit": commit_result,
            "push": push_result,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="commit_workspace_files")


@mcp_tool(write_action=False)
async def get_workspace_changes_summary(
    full_name: str,
    ref: str = "main",
    path_prefix: Optional[str] = None,
    max_files: int = 200,
) -> Dict[str, Any]:
    """Summarize modified, added, deleted, renamed, and untracked files in the workspace."""

    deps = _workspace_deps()
    effective_ref = _effective_ref_for_repo(full_name, ref)
    repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

    status_result = await deps["run_shell"](
        "git status --porcelain=v1", cwd=repo_dir, timeout_seconds=60
    )
    raw_status = status_result.get("stdout", "")
    lines = [line for line in raw_status.splitlines() if line.strip()]

    def _within_prefix(path: str) -> bool:
        if not path_prefix:
            return True
        prefix = path_prefix.rstrip("/")
        return path == prefix or path.startswith(prefix + "/")

    changes: List[Dict[str, Any]] = []
    summary = {
        "modified": 0,
        "added": 0,
        "deleted": 0,
        "renamed": 0,
        "untracked": 0,
    }

    for line in lines:
        if len(line) < 3:
            continue
        x = line[0]
        y = line[1]
        rest = line[3:]

        if " -> " in rest:
            src, dst = rest.split(" -> ", 1)
            path = dst
            change_type = "R"
        else:
            src = rest
            dst = None
            path = src
            change_type = "??" if x == "?" and y == "?" else "M"

        if not _within_prefix(path):
            continue

        if x == "?" and y == "?":
            summary["untracked"] += 1
        elif x == "A" or y == "A":
            change_type = "A"
            summary["added"] += 1
        elif x == "D" or y == "D":
            change_type = "D"
            summary["deleted"] += 1
        elif x == "R" or y == "R":
            change_type = "R"
            summary["renamed"] += 1
        else:
            change_type = "M"
            summary["modified"] += 1

        if len(changes) < max_files:
            changes.append(
                {
                    "status": change_type,
                    "path": path,
                    "src": src,
                    "dst": dst,
                }
            )

    has_changes = any(summary.values())
    return {
        "ref": effective_ref,
        "has_changes": has_changes,
        "summary": summary,
        "changes": changes,
    }



@mcp_tool(write_action=False)
async def run_tests(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the project's test command in the persistent workspace and summarize the result."""
    result = await run_command(
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        patch=patch,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )

    if isinstance(result, dict) and "error" in result:
        # Structured error from run_command (e.g. auth/clone failure).
        return {
            "status": "failed",
            "command": test_command,
            "error": result["error"],
            "controller_log": [
                "Test run failed due to a workspace or command error.",
                f"- Command: {test_command}",
                f"- Error: {result['error'].get('error')}",
            ],
        }

    if not isinstance(result, dict) or "result" not in result:
        # Unexpected shape from run_command.
        return {
            "status": "failed",
            "command": test_command,
            "error": {
                "error": "UnexpectedResultShape",
                "message": "run_command returned an unexpected result structure",
                "raw_result": result,
            },
            "controller_log": [
                "Test run failed because run_command returned an unexpected result shape.",
                f"- Command: {test_command}",
            ],
        }

    cmd_result = result.get("result") or {}
    exit_code = cmd_result.get("exit_code")
    status = "passed" if exit_code == 0 else "failed"

    summary_lines = [
        "Completed test command in workspace:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
        f"- Command: {test_command}",
        f"- Status: {status}",
        f"- Exit code: {exit_code}",
    ]

    return {
        "status": status,
        "command": test_command,
        "exit_code": exit_code,
        "repo_dir": result.get("repo_dir"),
        "workdir": result.get("workdir"),
        "result": cmd_result,
        "controller_log": summary_lines,
    }



@mcp_tool(write_action=False)
async def run_quality_suite(
    full_name: str,
    ref: str = "main",
    test_command: str = "pytest",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    lint_command: str = "ruff check .",
) -> Dict[str, Any]:
    """Run the standard quality/test suite for a repo/ref.

    For now this is a thin wrapper around `run_tests`, but it also emits a
    small `controller_log` so controllers can describe what happened.
    """
    tests_result = await run_tests(
        full_name=full_name,
        ref=ref,
        test_command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        patch=patch,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )

    status = tests_result.get("status") or "unknown"
    summary_lines = [
        "Quality suite run (tests only):",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
        f"- Test command: {test_command}",
        f"- Lint command (unused here): {lint_command}",
        f"- Test status: {status}",
    ]

    existing_log = tests_result.get("controller_log")
    if isinstance(existing_log, list):
        summary_lines.extend(existing_log)

    tests_result["controller_log"] = summary_lines
    return tests_result


@mcp_tool(write_action=False)
async def run_lint_suite(
    full_name: str,
    ref: str = "main",
    lint_command: str = "ruff check .",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    patch: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the lint or static-analysis command in the workspace."""
    result = await run_command(
        full_name=full_name,
        ref=ref,
        command=lint_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        patch=patch,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )

    if isinstance(result, dict) and "error" in result:
        return {
            "status": "failed",
            "command": lint_command,
            "error": result["error"],
            "controller_log": [
                "Lint run failed due to a workspace or command error.",
                f"- Command: {lint_command}",
                f"- Error: {result['error'].get('error')}",
            ],
        }

    if not isinstance(result, dict) or "result" not in result:
        return {
            "status": "failed",
            "command": lint_command,
            "error": {
                "error": "UnexpectedResultShape",
                "message": "run_command returned an unexpected result structure",
                "raw_result": result,
            },
            "controller_log": [
                "Lint run failed because run_command returned an unexpected result shape.",
                f"- Command: {lint_command}",
            ],
        }

    cmd_result = result.get("result") or {}
    exit_code = cmd_result.get("exit_code")
    status = "passed" if exit_code == 0 else "failed"

    summary_lines = [
        "Completed lint command in workspace:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
        f"- Command: {lint_command}",
        f"- Status: {status}",
        f"- Exit code: {exit_code}",
    ]

    return {
        "status": status,
        "command": lint_command,
        "exit_code": exit_code,
        "repo_dir": result.get("repo_dir"),
        "workdir": result.get("workdir"),
        "result": cmd_result,
        "controller_log": summary_lines,
    }



@mcp_tool(write_action=False)
async def build_pr_summary(
    full_name: str,
    ref: str,
    title: str,
    body: str,
    changed_files: Optional[List[str]] = None,
    tests_status: Optional[str] = None,
    lint_status: Optional[str] = None,
    breaking_changes: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build a normalized JSON summary for a pull request description."""
    return {
        "repo": full_name,
        "ref": ref,
        "title": title,
        "body": body,
        "changed_files": changed_files or [],
        "tests_status": tests_status or "unknown",
        "lint_status": lint_status or "unknown",
        "breaking_changes": bool(breaking_changes) if breaking_changes is not None else None,
    }
