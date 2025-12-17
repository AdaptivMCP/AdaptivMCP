"""Shared utilities for workspace tools.

Workspace-backed tools (clone, run commands, commit, and suites).
"""

# Split from github_mcp.tools_workspace (generated).
import os
import re
import shlex
import sys
from typing import Any, Dict, Optional

from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    CONTROLLER_REPO,
    _ensure_write_allowed,
)
from github_mcp.workspace import (
    _clone_repo,
    _prepare_temp_virtualenv,
    _run_shell,
)


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


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


async def _run_shell_ok(
    deps: Dict[str, Any], cmd: str, *, cwd: str, timeout_seconds: int
) -> Dict[str, Any]:
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
        line.strip() for line in (conflicted.get("stdout", "") or "").splitlines() if line.strip()
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

    default_branch = _tw()._default_branch_for_repo(full_name)
    if branch == default_branch:
        raise GitHubAPIError(f"Refusing to delete default branch {default_branch!r}")

    effective_ref = _tw()._effective_ref_for_repo(full_name, default_branch)
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
