"""Workspace and command tools for GitHub MCP."""

import os
import shutil
import time
import uuid
import shlex
import sys
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
from github_mcp.utils import _effective_ref_for_repo, _default_branch_for_repo
from github_mcp.workspace import (
    _clone_repo,
    _prepare_temp_virtualenv,
    _run_shell,
    _workspace_path,
)


# Guardrail: prevent token-like secret strings from being committed into repos.
# The scan only runs when the repo contains scripts/check_no_tokenlike_strings.py.


def _safe_branch_slug(value: str, *, max_len: int = 200) -> str:
    """Return a conservative branch slug derived from an arbitrary string."""

    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", (value or "").strip())
    cleaned = cleaned.strip("-/.")
    if not cleaned:
        cleaned = "branch"
    # Avoid invalid ref sequences.
    cleaned = cleaned.replace("..", "-").replace("@{", "-")
    cleaned = cleaned[:max_len]
    # Ensure it starts with an allowed character.
    if not re.match(r"^[A-Za-z0-9]", cleaned):
        cleaned = f"b-{cleaned}"[:max_len]
    return cleaned


async def _run_shell_ok(deps: Dict[str, Any], cmd: str, *, cwd: str, timeout_seconds: int) -> Dict[str, Any]:
    res = await deps["run_shell"](cmd, cwd=cwd, timeout_seconds=timeout_seconds)
    if res.get("exit_code", 0) != 0:
        stderr = res.get("stderr", "") or res.get("stdout", "")
        raise GitHubAPIError(f"Command failed: {cmd}: {stderr}")
    return res


def _git_state_markers(repo_dir: str) -> Dict[str, bool]:
    git_dir = os.path.join(repo_dir, ".git")
    return {
        "merge_in_progress": os.path.exists(os.path.join(git_dir, "MERGE_HEAD")),
        "rebase_in_progress": os.path.isdir(os.path.join(git_dir, "rebase-apply"))
        or os.path.isdir(os.path.join(git_dir, "rebase-merge")),
        "cherry_pick_in_progress": os.path.exists(os.path.join(git_dir, "CHERRY_PICK_HEAD")),
        "revert_in_progress": os.path.exists(os.path.join(git_dir, "REVERT_HEAD")),
    }


async def _diagnose_workspace_branch(
    deps: Dict[str, Any], *, repo_dir: str, expected_branch: str
) -> Dict[str, Any]:
    """Return lightweight diagnostics used to detect a mangled workspace."""

    diag: Dict[str, Any] = {"expected_branch": expected_branch}
    show_branch = await deps["run_shell"](
        "git branch --show-current", cwd=repo_dir, timeout_seconds=60
    )
    diag["show_current_exit_code"] = show_branch.get("exit_code")
    diag["current_branch"] = (show_branch.get("stdout", "") or "").strip() or None

    status = await deps["run_shell"]("git status --porcelain", cwd=repo_dir, timeout_seconds=60)
    diag["status_exit_code"] = status.get("exit_code")
    diag["status_is_clean"] = not (status.get("stdout", "") or "").strip()

    conflicted = await deps["run_shell"](
        "git diff --name-only --diff-filter=U", cwd=repo_dir, timeout_seconds=60
    )
    conflicted_files = [
        line.strip()
        for line in (conflicted.get("stdout", "") or "").splitlines()
        if line.strip()
    ]
    diag["conflicted_files"] = conflicted_files
    diag["has_conflicts"] = bool(conflicted_files)

    markers = _git_state_markers(repo_dir)
    diag.update(markers)

    detached_or_wrong_branch = diag["current_branch"] != expected_branch
    mangled = (
        detached_or_wrong_branch
        or markers["merge_in_progress"]
        or markers["rebase_in_progress"]
        or markers["cherry_pick_in_progress"]
        or markers["revert_in_progress"]
        or diag["has_conflicts"]
    )
    diag["mangled"] = mangled
    diag["detached_or_wrong_branch"] = detached_or_wrong_branch
    return diag


async def _delete_branch_via_workspace(
    deps: Dict[str, Any], *, full_name: str, branch: str
) -> Dict[str, Any]:
    """Delete a branch via git push (remote) + best-effort local deletion."""

    default_branch = _default_branch_for_repo(full_name)
    if branch == default_branch:
        raise GitHubAPIError(f"Refusing to delete default branch {default_branch!r}")

    effective_ref = _effective_ref_for_repo(full_name, default_branch)
    repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
    await deps["run_shell"](
        f"git checkout {shlex.quote(effective_ref)}", cwd=repo_dir, timeout_seconds=120
    )

    delete_remote = await deps["run_shell"](
        f"git push origin --delete {shlex.quote(branch)}", cwd=repo_dir, timeout_seconds=300
    )
    if delete_remote.get("exit_code", 0) != 0:
        stderr = delete_remote.get("stderr", "") or delete_remote.get("stdout", "")
        raise GitHubAPIError(f"git push origin --delete failed: {stderr}")

    delete_local = await deps["run_shell"](
        f"git branch -D {shlex.quote(branch)}", cwd=repo_dir, timeout_seconds=120
    )
    return {
        "repo_dir": repo_dir,
        "default_branch": default_branch,
        "deleted_branch": branch,
        "delete_remote": delete_remote,
        "delete_local": delete_local,
    }
TOKENLIKE_SCAN_COMMAND = (
    "if [ -f scripts/check_no_tokenlike_strings.py ]; then "
    "python scripts/check_no_tokenlike_strings.py; "
    "else echo 'token scan skipped: scripts/check_no_tokenlike_strings.py not found'; fi"
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
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        effective_ref = _effective_ref_for_repo(full_name, ref)

        # Prefer scoped write gating so feature-branch work is allowed even
        # when global WRITE_ALLOWED is disabled.
        try:
            deps["ensure_write_allowed"](
                f"set_workspace_file_contents {path} for {full_name}@{effective_ref}",
                target_ref=effective_ref,
            )
        except TypeError:
            deps["ensure_write_allowed"](
                f"set_workspace_file_contents {path} for {full_name}@{effective_ref}"
            )

        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        write_info = _workspace_write_text(
            repo_dir,
            path,
            content,
            create_parents=create_parents,
        )

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "status": "written",
            **write_info,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="set_workspace_file_contents", path=path)




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
async def terminal_command(
    full_name: Optional[str] = None,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
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
                "split it into smaller commands or check in a script into the repo and run it from the workspace."
            )
        needs_write_gate = (
            mutating
            or installing_dependencies
            or not use_temp_venv
        )
        if needs_write_gate:
            # Prefer scoped write gating so feature-branch work is allowed even
            # when global WRITE_ALLOWED is disabled.
            try:
                deps["ensure_write_allowed"](
                    f"terminal_command {command} in {full_name}@{effective_ref}",
                    target_ref=effective_ref,
                )
            except TypeError:
                # Backwards-compat: older implementations accept only (context).
                deps["ensure_write_allowed"](
                    f"terminal_command {command} in {full_name}@{effective_ref}"
                )
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
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
                    stderr = install_result.get("stderr") or ""
                    stdout = install_result.get("stdout") or ""
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
            stderr = result.get("stderr") or ""
            stdout = result.get("stdout") or ""
            combined = f"{stderr}\n{stdout}"
            mm = re.search(
                r"ModuleNotFoundError: No module named ['\"]([^'\"]+)['\"]",
                combined,
            )
            if mm:
                out["dependency_hint"] = {
                    "missing_module": mm.group(1),
                    "message": "Missing python dependency. Re-run terminal_command with installing_dependencies=true.",
                }

        return out
    except Exception as exc:
        return _structured_tool_error(exc, context="terminal_command")


@mcp_tool(write_action=False)
async def run_command(
    full_name: Optional[str] = None,
    ref: str = "main",
    command: str = "pytest",
    timeout_seconds: int = 300,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Deprecated alias for terminal_command.

    Use terminal_command for a clearer "terminal/PC gateway" mental model.
    """

    out = await terminal_command(
        full_name=full_name,
        ref=ref,
        command=command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
        owner=owner,
        repo=repo,
        branch=branch,
    )
    if isinstance(out, dict):
        log = out.get("controller_log")
        if not isinstance(log, list):
            log = []
        log.insert(0, "run_command is deprecated; use terminal_command instead.")
        out["controller_log"] = log
    return out


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
async def workspace_delete_branch(
    full_name: Optional[str] = None,
    branch: str = "",
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> Dict[str, Any]:
    """Delete a non-default branch using the workspace clone.

    This is the workspace counterpart to branch-creation helpers and is intended
    for closing out ephemeral feature branches once their work has been merged.
    """

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)

        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("branch must be a non-empty string")

        branch = branch.strip()

        # Conservative branch-name validation (mirror workspace_create_branch).
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch):
            raise ValueError("branch contains invalid characters")
        if ".." in branch or "@{" in branch:
            raise ValueError("branch contains invalid ref sequence")
        if branch.startswith("/") or branch.endswith("/"):
            raise ValueError("branch must not start or end with '/'")
        if branch.endswith(".lock"):
            raise ValueError("branch must not end with '.lock'")

        default_branch = _default_branch_for_repo(full_name)
        if branch == default_branch:
            raise GitHubAPIError(
                f"Refusing to delete default branch {default_branch!r}; "
                "delete it manually in GitHub if this is truly desired."
            )

        # Normalize to the default branch for workspace operations so we are not
        # checked out on the branch we are about to delete.
        effective_ref = _effective_ref_for_repo(full_name, default_branch)

        _ensure_write_allowed(
            f"workspace_delete_branch {branch} for {full_name}@{effective_ref}",
            target_ref=effective_ref,
        )

        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        # Ensure the working copy is on the effective ref.
        await deps["run_shell"](
            f"git checkout {shlex.quote(effective_ref)}",
            cwd=repo_dir,
            timeout_seconds=120,
        )

        # Delete remote first; if the remote delete fails, surface that.
        delete_remote = await deps["run_shell"](
            f"git push origin --delete {shlex.quote(branch)}",
            cwd=repo_dir,
            timeout_seconds=300,
        )
        if delete_remote.get("exit_code", 0) != 0:
            stderr = delete_remote.get("stderr", "") or delete_remote.get("stdout", "")
            raise GitHubAPIError(f"git push origin --delete failed: {stderr}")

        # Then delete local branch if it exists. If it does not, treat that as best-effort.
        delete_local = await deps["run_shell"](
            f"git branch -D {shlex.quote(branch)}",
            cwd=repo_dir,
            timeout_seconds=120,
        )

        return {
            "repo_dir": repo_dir,
            "default_branch": default_branch,
            "deleted_branch": branch,
            "delete_remote": delete_remote,
            "delete_local": delete_local,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_delete_branch")




@mcp_tool(write_action=True)
async def workspace_self_heal_branch(
    full_name: Optional[str] = None,
    branch: str = "",
    *,
    base_ref: str = "main",
    new_branch: Optional[str] = None,
    discard_uncommitted_changes: bool = True,
    delete_mangled_branch: bool = True,
    reset_base: bool = True,
    enumerate_repo: bool = True,
    dry_run: bool = False,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
) -> Dict[str, Any]:
    """Detect a mangled workspace branch and recover to a fresh branch.

    This tool is intended to be used by assistants mid-flow when a workspace
    clone becomes inconsistent (wrong branch checked out, merge/rebase state,
    conflicts, etc.). When healing, it:

      1) Diagnoses the workspace clone for ``branch``.
      2) Optionally deletes the mangled branch (remote + best-effort local).
      3) Resets the base branch workspace (default: ``main``).
      4) Creates + pushes a new fresh branch.
      5) Ensures a clean clone for the new branch.
      6) Optionally returns a small repo snapshot to rebuild "mental state".

    Returns plain-language step logs for UI rendering.
    """

    try:
        deps = _workspace_deps()
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)

        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("branch must be a non-empty string")
        branch = branch.strip()

        # Conservative branch-name validation (mirror workspace_create_branch).
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", branch):
            raise ValueError("branch contains invalid characters")
        if ".." in branch or "@{" in branch:
            raise ValueError("branch contains invalid ref sequence")
        if branch.startswith("/") or branch.endswith("/"):
            raise ValueError("branch must not start or end with '/'")
        if branch.endswith(".lock"):
            raise ValueError("branch must not end with '.lock'")

        effective_base = _effective_ref_for_repo(full_name, base_ref)
        _ensure_write_allowed(
            f"workspace_self_heal_branch {branch} for {full_name}@{effective_base}",
            target_ref=effective_base,
        )

        steps: List[Dict[str, Any]] = []

        def step(action: str, detail: str, *, status: str = "ok", **extra: Any) -> None:
            payload: Dict[str, Any] = {
                "ts": time.time(),
                "action": action,
                "detail": detail,
                "status": status,
            }
            payload.update(extra)
            steps.append(payload)

        step(
            "Start self-heal",
            f"Checking whether branch '{branch}' is in a safe git state (repo {full_name}).",
        )

        branch_repo_dir = await deps["clone_repo"](full_name, ref=branch, preserve_changes=True)
        diag = await _diagnose_workspace_branch(
            deps, repo_dir=branch_repo_dir, expected_branch=branch
        )
        step(
            "Diagnose branch",
            f"Current branch is {diag.get('current_branch')!r}; expected {branch!r}.",
            diagnostics=diag,
        )

        if not diag.get("mangled"):
            step(
                "No action",
                f"Branch '{branch}' looks healthy; no recovery needed.",
            )
            return {
                "full_name": full_name,
                "branch": branch,
                "base_ref": effective_base,
                "mangled": False,
                "healed": False,
                "steps": steps,
                "diagnostics": diag,
            }

        if not diag.get("status_is_clean") and not discard_uncommitted_changes:
            raise GitHubAPIError(
                "Uncommitted changes detected in the workspace; set discard_uncommitted_changes=true to proceed."
            )

        if dry_run:
            step(
                "Dry run",
                "Detected a mangled workspace; would delete/reset/recreate a branch, but dry_run=true.",
            )
            return {
                "full_name": full_name,
                "branch": branch,
                "base_ref": effective_base,
                "mangled": True,
                "healed": False,
                "would_heal": True,
                "steps": steps,
                "diagnostics": diag,
            }

        # Remove the local workspace dir for the mangled branch (forces a clean re-clone later).
        mangled_workspace_dir = _workspace_path(full_name, _effective_ref_for_repo(full_name, branch))
        if os.path.isdir(mangled_workspace_dir):
            shutil.rmtree(mangled_workspace_dir)
            step(
                "Remove local workspace",
                f"Deleted local workspace directory for '{branch}'.",
                repo_dir=mangled_workspace_dir,
            )

        delete_result = None
        if delete_mangled_branch:
            step(
                "Delete branch",
                f"Deleting branch '{branch}' on origin (and cleaning local refs).",
            )
            delete_result = await _delete_branch_via_workspace(
                deps, full_name=full_name, branch=branch
            )
            step(
                "Delete branch",
                f"Deleted '{branch}' from origin.",
                deleted_branch=branch,
            )
        else:
            step(
                "Skip delete",
                f"Keeping branch '{branch}' (delete_mangled_branch=false).",
            )

        # Reset base branch workspace.
        if reset_base:
            base_repo_dir = await deps["clone_repo"](
                full_name, ref=effective_base, preserve_changes=False
            )
            step(
                "Reset base",
                f"Reset local workspace for base ref '{effective_base}'.",
                repo_dir=base_repo_dir,
            )
        else:
            base_repo_dir = await deps["clone_repo"](
                full_name, ref=effective_base, preserve_changes=True
            )
            step(
                "Base ready",
                f"Using existing base workspace for '{effective_base}' without resetting.",
                repo_dir=base_repo_dir,
            )

        # Create a fresh branch.
        if new_branch:
            candidate = new_branch
        else:
            candidate = f"heal/{_safe_branch_slug(branch, max_len=120)}-{uuid.uuid4().hex[:8]}"
        candidate = _safe_branch_slug(candidate)

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}", candidate):
            raise ValueError("new_branch contains invalid characters")
        if ".." in candidate or "@{" in candidate:
            raise ValueError("new_branch contains invalid ref sequence")
        if candidate.startswith("/") or candidate.endswith("/"):
            raise ValueError("new_branch must not start or end with '/'")
        if candidate.endswith(".lock"):
            raise ValueError("new_branch must not end with '.lock'")

        step(
            "Create fresh branch",
            f"Creating and pushing new branch '{candidate}' from '{effective_base}'.",
            new_branch=candidate,
        )

        await _run_shell_ok(
            deps,
            f"git checkout {shlex.quote(effective_base)}",
            cwd=base_repo_dir,
            timeout_seconds=120,
        )
        await _run_shell_ok(
            deps,
            f"git checkout -b {shlex.quote(candidate)}",
            cwd=base_repo_dir,
            timeout_seconds=120,
        )
        await _run_shell_ok(
            deps,
            f"git push -u origin {shlex.quote(candidate)}",
            cwd=base_repo_dir,
            timeout_seconds=300,
        )

        # Ensure a clean clone for the new branch.
        new_repo_dir = await deps["clone_repo"](full_name, ref=candidate, preserve_changes=False)
        step(
            "Fresh workspace ready",
            f"Created a clean workspace for '{candidate}'.",
            repo_dir=new_repo_dir,
        )

        snapshot: Dict[str, Any] = {}
        if enumerate_repo:
            log_res = await deps["run_shell"](
                "git log -n 1 --oneline", cwd=new_repo_dir, timeout_seconds=60
            )
            st_res = await deps["run_shell"](
                "git status --porcelain", cwd=new_repo_dir, timeout_seconds=60
            )

            # Top-level entries (trim to keep responses small).
            try:
                entries = [e for e in sorted(os.listdir(new_repo_dir)) if e not in {".git", ".venv-mcp"}]
            except Exception:
                entries = []

            # Count files excluding .git and .venv-mcp.
            file_count = 0
            for root, dirs, files in os.walk(new_repo_dir):
                dirs[:] = [d for d in dirs if d not in {".git", ".venv-mcp"}]
                file_count += len(files)

            snapshot = {
                "head": (log_res.get("stdout", "") or "").strip() or None,
                "clean": not (st_res.get("stdout", "") or "").strip(),
                "top_level": entries[:50],
                "file_count": file_count,
            }
            step(
                "Enumerate repo",
                f"Captured a small snapshot of '{candidate}' to rebuild context.",
                snapshot=snapshot,
            )

        return {
            "full_name": full_name,
            "branch": branch,
            "base_ref": effective_base,
            "mangled": True,
            "healed": True,
            "deleted": bool(delete_result) if delete_mangled_branch else False,
            "new_branch": candidate,
            "repo_dir": new_repo_dir,
            "steps": steps,
            "diagnostics": diag,
            "snapshot": snapshot,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_self_heal_branch")
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
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the project's test command in the persistent workspace and summarize the result."""
    result = await terminal_command(
        full_name=full_name,
        ref=ref,
        command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
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
                "message": "terminal_command returned an unexpected result structure",
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
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    lint_command: str = "ruff check .",
    run_tokenlike_scan: bool = True,
) -> Dict[str, Any]:
    """Run the standard quality/test suite for a repo/ref.

    This executes, in order:
      1) Optional token-like string scan (only if the repo contains the scanner script)
      2) Lint/static analysis via `run_lint_suite`
      3) Tests via `run_tests`

    The scan step helps prevent upstream OpenAI blocks and accidental leakage by
    ensuring token-shaped strings are not committed into docs/tests/examples.
    """

    controller_log: List[str] = [
        "Quality suite run:",
        f"- Repo: {full_name}",
        f"- Ref: {ref}",
        f"- Token-like scan: {'enabled' if run_tokenlike_scan else 'disabled'}",
        f"- Lint command: {lint_command}",
        f"- Test command: {test_command}",
    ]

    if run_tokenlike_scan:
        scan_result = await terminal_command(
            full_name=full_name,
            ref=ref,
            command=TOKENLIKE_SCAN_COMMAND,
            timeout_seconds=min(timeout_seconds, 300),
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=installing_dependencies,
            mutating=mutating,
        )
        if isinstance(scan_result, dict) and "error" in scan_result:
            return {
                "status": "failed",
                "command": TOKENLIKE_SCAN_COMMAND,
                "error": scan_result["error"],
                "controller_log": controller_log
                + ["Token-like scan failed due to a workspace/command error."],
            }
        cmd = (scan_result or {}).get("result") or {}
        exit_code = cmd.get("exit_code")
        if exit_code not in (0, None):
            return {
                "status": "failed",
                "command": TOKENLIKE_SCAN_COMMAND,
                "exit_code": exit_code,
                "repo_dir": scan_result.get("repo_dir"),
                "workdir": scan_result.get("workdir"),
                "result": cmd,
                "controller_log": controller_log
                + ["Token-like scan failed; replace secrets with <REDACTED> placeholders."],
            }
        controller_log.append("- Token-like scan: passed (or skipped)")

    lint_result = await run_lint_suite(
        full_name=full_name,
        ref=ref,
        lint_command=lint_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
        run_tokenlike_scan=False,
    )
    if (lint_result or {}).get("status") != "passed":
        lint_result.setdefault("controller_log", controller_log + ["- Lint: failed"])
        return lint_result
    controller_log.append("- Lint: passed")

    tests_result = await run_tests(
        full_name=full_name,
        ref=ref,
        test_command=test_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
        use_temp_venv=use_temp_venv,
        installing_dependencies=installing_dependencies,
        mutating=mutating,
    )
    status = tests_result.get("status") or "unknown"
    controller_log.append(f"- Tests: {status}")

    existing_log = tests_result.get("controller_log")
    if isinstance(existing_log, list):
        controller_log.extend(existing_log)

    tests_result["controller_log"] = controller_log
    return tests_result


@mcp_tool(write_action=False)
async def run_lint_suite(
    full_name: str,
    ref: str = "main",
    lint_command: str = "ruff check .",
    timeout_seconds: int = 600,
    workdir: Optional[str] = None,
    use_temp_venv: bool = True,
    installing_dependencies: bool = False,
    mutating: bool = False,
    *,
    run_tokenlike_scan: bool = True,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Run the lint or static-analysis command in the workspace."""

    if run_tokenlike_scan:
        scan_result = await terminal_command(
            full_name=full_name,
            ref=ref,
            command=TOKENLIKE_SCAN_COMMAND,
            timeout_seconds=min(timeout_seconds, 300),
            workdir=workdir,
            use_temp_venv=use_temp_venv,
            installing_dependencies=installing_dependencies,
            mutating=mutating,
        )
        if isinstance(scan_result, dict) and "error" in scan_result:
            return {
                "status": "failed",
                "command": TOKENLIKE_SCAN_COMMAND,
                "error": scan_result["error"],
                "controller_log": [
                    "Token-like scan failed due to a workspace or command error.",
                    f"- Repo: {full_name}",
                    f"- Ref: {ref}",
                ],
            }
        cmd = (scan_result or {}).get("result") or {}
        exit_code = cmd.get("exit_code")
        if exit_code not in (0, None):
            return {
                "status": "failed",
                "command": TOKENLIKE_SCAN_COMMAND,
                "exit_code": exit_code,
                "repo_dir": scan_result.get("repo_dir"),
                "workdir": scan_result.get("workdir"),
                "result": cmd,
                "controller_log": [
                    "Token-like scan failed; replace secrets with <REDACTED> placeholders.",
                    f"- Repo: {full_name}",
                    f"- Ref: {ref}",
                ],
            }

    result = await terminal_command(
        full_name=full_name,
        ref=ref,
        command=lint_command,
        timeout_seconds=timeout_seconds,
        workdir=workdir,
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
                "message": "terminal_command returned an unexpected result structure",
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
