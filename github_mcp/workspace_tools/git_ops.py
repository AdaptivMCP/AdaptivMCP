# Split from github_mcp.tools_workspace (generated).
import os
import shutil
import time
import shlex
import re
from typing import Any, Dict, List, Optional

from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)

from ._shared import (
    _safe_branch_slug,
    _run_shell_ok,
    _diagnose_workspace_branch,
    _delete_branch_via_workspace,
)

async def _workspace_sync_snapshot(
    deps: Dict[str, Any],
    *,
    repo_dir: str,
    branch: str,
) -> Dict[str, Any]:
    fetch = await _run_shell_ok(
        deps,
        "git fetch --prune origin",
        cwd=repo_dir,
        timeout_seconds=300,
    )
    remote_ref = f"origin/{branch}"
    head = await _run_shell_ok(deps, "git rev-parse HEAD", cwd=repo_dir, timeout_seconds=60)
    remote = await _run_shell_ok(
        deps,
        f"git rev-parse {shlex.quote(remote_ref)}",
        cwd=repo_dir,
        timeout_seconds=60,
    )
    rev_list = await _run_shell_ok(
        deps,
        f"git rev-list --left-right --count HEAD...{shlex.quote(remote_ref)}",
        cwd=repo_dir,
        timeout_seconds=120,
    )
    counts = (rev_list.get("stdout", "") or "").strip().split()
    if len(counts) != 2:
        raise GitHubAPIError(
            f"Unexpected git rev-list output for {remote_ref}: {rev_list.get('stdout', '')}"
        )
    ahead = int(counts[0])
    behind = int(counts[1])

    status = await _run_shell_ok(
        deps,
        "git status --porcelain",
        cwd=repo_dir,
        timeout_seconds=60,
    )
    status_lines = [
        line
        for line in (status.get("stdout", "") or "").splitlines()
        if line.strip()
    ]

    return {
        "fetch": fetch,
        "remote_ref": remote_ref,
        "local_sha": (head.get("stdout", "") or "").strip(),
        "remote_sha": (remote.get("stdout", "") or "").strip(),
        "ahead": ahead,
        "behind": behind,
        "status_lines": status_lines,
        "is_clean": not status_lines,
        "diverged": bool(ahead or behind),
    }

def _tw():
    from github_mcp import tools_workspace as tw
    return tw

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

    This exists because some direct GitHub-API branch-creation calls can be unavailable in some environments.
    """

    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        base_ref = _tw()._resolve_ref(base_ref, branch=branch)
        effective_base = _tw()._effective_ref_for_repo(full_name, base_ref)

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
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)

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

        default_branch = _tw()._default_branch_for_repo(full_name)
        if branch == default_branch:
            raise GitHubAPIError(
                f"Refusing to delete default branch {default_branch!r}; "
                "delete it manually in GitHub if this is truly desired."
            )

        # Normalize to the default branch for workspace operations so we are not
        # checked out on the branch we are about to delete.
        effective_ref = _tw()._effective_ref_for_repo(full_name, default_branch)

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
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)

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

        effective_base = _tw()._effective_ref_for_repo(full_name, base_ref)
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
        mangled_workspace_dir = _tw()._workspace_path(full_name, _tw()._effective_ref_for_repo(full_name, branch))
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
            candidate = f"heal/{_safe_branch_slug(branch, max_len=120)}-{_tw().uuid.uuid4().hex[:8]}"
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

        # Use the freshly checked out local workspace for the new branch.
        new_repo_dir = base_repo_dir
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
            "steps": steps,
            "diagnostics": diag,
            "snapshot": snapshot,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_self_heal_branch")


@mcp_tool(write_action=False)
async def workspace_sync_status(
    full_name: Optional[str] = None,
    ref: str = "main",
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Report how a workspace clone differs from its remote branch."""
    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        snapshot = await _workspace_sync_snapshot(deps, repo_dir=repo_dir, branch=effective_ref)
        snapshot.update(
            {
                "branch": effective_ref,
                "full_name": full_name,
                "repo_dir": repo_dir,
            }
        )
        return snapshot
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_sync_status")


@mcp_tool(write_action=True)
async def workspace_sync_to_remote(
    full_name: Optional[str] = None,
    ref: str = "main",
    *,
    discard_local_changes: bool = False,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Reset a workspace clone to match the remote branch."""
    try:
        deps = _tw()._workspace_deps()
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        before = await _workspace_sync_snapshot(deps, repo_dir=repo_dir, branch=effective_ref)

        if (not discard_local_changes) and (not before["is_clean"] or before["ahead"] > 0):
            raise GitHubAPIError(
                "Workspace has local changes or unpushed commits. "
                "Re-run with discard_local_changes=true to force sync."
            )

        await _run_shell_ok(
            deps,
            f"git reset --hard {shlex.quote(before['remote_ref'])}",
            cwd=repo_dir,
            timeout_seconds=300,
        )
        if discard_local_changes:
            await _run_shell_ok(
                deps,
                "git clean -fd",
                cwd=repo_dir,
                timeout_seconds=120,
            )

        after = await _workspace_sync_snapshot(deps, repo_dir=repo_dir, branch=effective_ref)
        return {
            "branch": effective_ref,
            "full_name": full_name,
            "repo_dir": repo_dir,
            "discard_local_changes": discard_local_changes,
            "before": before,
            "after": after,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_sync_to_remote")
