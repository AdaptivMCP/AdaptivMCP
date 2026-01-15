# Split from github_mcp.tools_workspace (generated).
import os
import shlex
from typing import Any, Dict, Optional

from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import CONTROLLER_REPO
from github_mcp.utils import _get_main_module
from github_mcp.workspace import (
    _clone_repo,
    _prepare_temp_virtualenv,
    _run_shell,
    _git_auth_env,
    _apply_patch_to_repo,
)


def _cmd_invokes_git(cmd: object) -> bool:
    """Return True if a shell command string invokes git anywhere as a command segment.

    This handles composite commands like: "rm -rf x && git clone ...".
    Used only to decide whether to inject git auth env.
    """
    if not isinstance(cmd, str):
        return False
    s = cmd.strip()
    if not s:
        return False
    if s.startswith("git "):
        return True
    # Treat newlines as command separators.
    s = s.replace("\n", ";")
    for sep in ("&&", "||", ";", "|"):
        if sep in s:
            parts = s.split(sep)
            for part in parts[1:]:
                if part.lstrip().startswith("git "):
                    return True
    return False


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


def _safe_branch_slug(value: str) -> str:
    """Return a conservative branch slug derived from an arbitrary string."""
    raw = (value or "").strip()
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._/-")
    # Replace any disallowed runs with a single '-'.
    parts: list[str] = []
    prev_dash = False
    for ch in raw:
        if ch in allowed:
            parts.append(ch)
            prev_dash = False
        else:
            if not prev_dash:
                parts.append("-")
                prev_dash = True
    cleaned = "".join(parts).strip("-/.")
    if not cleaned:
        cleaned = "branch"
    # Avoid invalid ref sequences.
    cleaned = cleaned.replace("..", "-").replace("@{", "-")
    # Ensure it starts with an allowed character.
    if cleaned and not cleaned[0].isalnum():
        cleaned = f"b-{cleaned}"
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
    """Return lightweight diagnostics used to detect a mangled repo mirror."""
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
        f"git push origin --delete {shlex.quote(branch)}",
        cwd=repo_dir,
        timeout_seconds=300,
    )
    if delete_remote.get("exit_code", 0) != 0:
        stderr = delete_remote.get("stderr", "") or delete_remote.get("stdout", "")
        raise GitHubAPIError(f"git push origin --delete failed: {stderr}")

    delete_local = await deps["run_shell"](
        f"git branch -D {shlex.quote(branch)}", cwd=repo_dir, timeout_seconds=120
    )
    return {
        "default_branch": default_branch,
        "deleted_branch": branch,
        "delete_remote": delete_remote,
        "delete_local": delete_local,
    }


def _workspace_deps() -> Dict[str, Any]:
    """
    Return workspace dependencies.

    Important change: wrap run_shell so that any git command automatically
    receives the GitHub auth header env (GIT_HTTP_EXTRAHEADER + config-env),
    enabling `git push`/`git fetch` in non-interactive environments.
    """
    main_module = _get_main_module()
    clone_repo_fn = getattr(main_module, "_clone_repo", _clone_repo)
    base_run_shell = getattr(main_module, "_run_shell", _run_shell)
    prepare_venv_fn = getattr(main_module, "_prepare_temp_virtualenv", _prepare_temp_virtualenv)

    async def run_shell_with_git_auth(
        cmd: str,
        *,
        cwd: Optional[str] = None,
        timeout_seconds: int = 300,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        merged: Dict[str, str] = {}
        if env:
            merged.update(env)

        # Only inject auth for git commands (keeps non-git commands untouched).
        if _cmd_invokes_git(cmd):
            for k, v in _git_auth_env().items():
                merged.setdefault(k, v)

        return await base_run_shell(
            cmd,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            env=(merged if merged else None),
        )

    return {
        "clone_repo": clone_repo_fn,
        "run_shell": run_shell_with_git_auth,
        "prepare_temp_virtualenv": prepare_venv_fn,
        "apply_patch_to_repo": _apply_patch_to_repo,
    }


def _resolve_full_name(
    full_name: Optional[str], *, owner: Optional[str] = None, repo: Optional[str] = None
) -> str:
    """Resolve a repository identifier.

    Canonical identifier is `full_name` ("owner/repo").

    For backwards compatibility, some internal tool wrappers still pass legacy
    alias parameters (owner, repo). Those are accepted here to avoid runtime
    failures even though the external tool schema prefers `full_name`.
    """

    if isinstance(full_name, str) and full_name.strip():
        return full_name.strip()

    # Back-compat: allow callers to provide owner+repo instead of full_name.
    if isinstance(owner, str) and owner.strip() and isinstance(repo, str) and repo.strip():
        return owner.strip() + "/" + repo.strip()

    return CONTROLLER_REPO


def _resolve_ref(ref: str) -> str:
    """Return the git ref to operate on.

    The only supported ref selector is `ref`.
    """

    return ref
