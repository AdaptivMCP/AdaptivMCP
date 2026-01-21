# Split from github_mcp.tools_workspace (generated).
import os
import shlex
import shutil
import time
from typing import Any

from github_mcp import config
from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)
from github_mcp.utils import _normalize_timeout_seconds
from github_mcp.workspace import _workspace_path

from ._shared import (
    _delete_branch_via_workspace,
    _diagnose_workspace_branch,
    _resolve_full_name,
    _resolve_ref,
    _run_shell_ok,
    _safe_branch_slug,
    _tw,
)


def _slim_shell_result(result: Any) -> dict[str, Any]:
    """Return a connector-safe view of a run_shell result without truncation."""
    if not isinstance(result, dict):
        return {"raw": str(result)}
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    # Bound very large outputs.
    if len(stdout) > 4000:
        stdout = stdout[:4000] + "…"
    if len(stderr) > 4000:
        stderr = stderr[:4000] + "…"
    return {
        "exit_code": result.get("exit_code"),
        "timed_out": result.get("timed_out", False),
        "stdout": stdout,
        "stderr": stderr,
    }


def _shell_error(action: str, result: Any) -> GitHubAPIError:
    """Create a consistent GitHubAPIError from a run_shell result."""
    if not isinstance(result, dict):
        return GitHubAPIError(f"{action} failed: {result!r}")
    exit_code = result.get("exit_code")
    timed_out = bool(result.get("timed_out", False))
    stderr = (result.get("stderr") or "").strip()
    stdout = (result.get("stdout") or "").strip()
    detail = stderr or stdout
    if len(detail) > 4000:
        detail = detail[:4000] + "…"
    return GitHubAPIError(
        f"{action} failed (exit_code={exit_code}, timed_out={timed_out}): {detail}"
    )


async def _workspace_sync_snapshot(
    deps: dict[str, Any],
    *,
    repo_dir: str,
    branch: str,
) -> dict[str, Any]:
    t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)
    fetch = await _run_shell_ok(
        deps,
        "git fetch --prune origin",
        cwd=repo_dir,
        timeout_seconds=t_default,
    )
    remote_ref = f"origin/{branch}"
    head = await _run_shell_ok(deps, "git rev-parse HEAD", cwd=repo_dir, timeout_seconds=t_default)
    remote = await _run_shell_ok(
        deps,
        f"git rev-parse {shlex.quote(remote_ref)}",
        cwd=repo_dir,
        timeout_seconds=t_default,
    )
    rev_list = await _run_shell_ok(
        deps,
        f"git rev-list --left-right --count HEAD...{shlex.quote(remote_ref)}",
        cwd=repo_dir,
        timeout_seconds=t_default,
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
        timeout_seconds=t_default,
    )
    status_lines = [line for line in (status.get("stdout", "") or "").splitlines() if line.strip()]

    return {
        "fetch": _slim_shell_result(fetch),
        "remote_ref": remote_ref,
        "local_sha": (head.get("stdout", "") or "").strip(),
        "remote_sha": (remote.get("stdout", "") or "").strip(),
        "ahead": ahead,
        "behind": behind,
        "status_lines": status_lines,
        "is_clean": not status_lines,
        "diverged": bool(ahead or behind),
    }


def _parse_git_numstat(stdout: str) -> list[dict[str, Any]]:
    """Parse `git diff --numstat` output into a structured list."""
    out: list[dict[str, Any]] = []
    for raw in (stdout or "").splitlines():
        if not raw.strip():
            continue
        # Format: <added>\t<removed>\t<path>
        parts = raw.split("\t")
        if len(parts) < 3:
            continue
        added_s, removed_s = parts[0].strip(), parts[1].strip()
        path = "\t".join(parts[2:]).strip()

        def _to_int(v: str) -> int | None:
            if v == "-":
                return None
            try:
                return int(v)
            except Exception:
                return None

        out.append(
            {
                "path": path,
                "added": _to_int(added_s),
                "removed": _to_int(removed_s),
                "is_binary": (added_s == "-" or removed_s == "-"),
            }
        )
    return out


@mcp_tool(write_action=False)
async def workspace_git_diff(
    full_name: str | None = None,
    ref: str = "main",
    *,
    left_ref: str | None = None,
    right_ref: str | None = None,
    staged: bool = False,
    paths: list[str] | None = None,
    context_lines: int = 3,
    max_chars: int = 200_000,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Return a git diff from the workspace mirror.

    Supports:
      - comparing two refs (left_ref vs right_ref)
      - comparing a ref vs working tree (set one side)
      - comparing staged changes vs HEAD (staged=true)

    The returned diff is unified and includes hunk headers with line ranges.
    """

    try:
        if not isinstance(context_lines, int) or context_lines < 0:
            raise ValueError("context_lines must be an int >= 0")
        if not isinstance(max_chars, int) or max_chars < 1:
            raise ValueError("max_chars must be an int >= 1")
        if paths is None:
            paths = []
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise TypeError("paths must be a list of strings")

        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        left = left_ref.strip() if isinstance(left_ref, str) and left_ref.strip() else None
        right = right_ref.strip() if isinstance(right_ref, str) and right_ref.strip() else None
        path_args = ""
        if paths:
            quoted = " ".join(shlex.quote(p.strip()) for p in paths if p.strip())
            if quoted:
                path_args = f" -- {quoted}"

        base = f"git diff --no-color --unified={int(context_lines)}"
        numstat_base = "git diff --numstat"
        if staged:
            diff_cmd = f"{base} --cached{path_args}"
            numstat_cmd = f"{numstat_base} --cached{path_args}"
        else:
            if left and right:
                diff_cmd = f"{base} {shlex.quote(left)} {shlex.quote(right)}{path_args}"
                numstat_cmd = f"{numstat_base} {shlex.quote(left)} {shlex.quote(right)}{path_args}"
            elif left and not right:
                diff_cmd = f"{base} {shlex.quote(left)}{path_args}"
                numstat_cmd = f"{numstat_base} {shlex.quote(left)}{path_args}"
            elif right and not left:
                # Compare working tree to a right ref by swapping order.
                diff_cmd = f"{base} {shlex.quote(right)}{path_args}"
                numstat_cmd = f"{numstat_base} {shlex.quote(right)}{path_args}"
            else:
                diff_cmd = f"{base}{path_args}"
                numstat_cmd = f"{numstat_base}{path_args}"

        diff_res = await deps["run_shell"](
            diff_cmd,
            cwd=repo_dir,
            timeout_seconds=_normalize_timeout_seconds(
                config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0
            ),
        )
        if diff_res.get("exit_code", 0) != 0:
            raise _shell_error("git diff", diff_res)
        diff_text = diff_res.get("stdout", "") or ""
        truncated = False
        if len(diff_text) > int(max_chars):
            diff_text = diff_text[: int(max_chars)]
            truncated = True

        numstat_res = await deps["run_shell"](
            numstat_cmd,
            cwd=repo_dir,
            timeout_seconds=_normalize_timeout_seconds(
                config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0
            ),
        )
        numstat = _parse_git_numstat(numstat_res.get("stdout", "") or "")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "left_ref": left,
            "right_ref": right,
            "staged": bool(staged),
            "paths": paths,
            "context_lines": int(context_lines),
            "diff": diff_text,
            "truncated": bool(truncated),
            "numstat": numstat,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_diff")


@mcp_tool(write_action=True)
async def workspace_create_branch(
    full_name: str | None = None,
    base_ref: str = "main",
    new_branch: str = "",
    push: bool = True,
    *,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Create a branch using the repo mirror (workspace clone), optionally pushing to origin.

    This exists because some direct GitHub-API branch-creation calls can be unavailable in some environments.
    """

    try:
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        base_ref = _resolve_ref(base_ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_base = _tw()._effective_ref_for_repo(full_name, base_ref)

        if not isinstance(new_branch, str) or not new_branch:
            raise ValueError("new_branch must be a non-empty string")

        # IMPORTANT: the workspace mirror is keyed by `ref`. If we create +
        # checkout a new branch *inside* the base mirror directory, subsequent
        # calls that operate on the new branch will use a different mirror
        # directory and appear to "lose" local changes. To keep mirrors
        # consistent we:
        # 1) create the branch in the base mirror (preserves uncommitted changes)
        # 2) move that working copy directory to the new branch mirror directory
        # 3) recreate a clean base mirror directory from origin
        repo_dir = await deps["clone_repo"](full_name, ref=effective_base, preserve_changes=True)

        checkout = await deps["run_shell"](
            f"git checkout -b {shlex.quote(new_branch)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )
        if checkout.get("exit_code", 0) != 0:
            raise _shell_error("git checkout -b", checkout)

        push_result = None
        if push:
            push_result = await deps["run_shell"](
                f"git push -u origin {shlex.quote(new_branch)}",
                cwd=repo_dir,
                timeout_seconds=t_default,
            )
            if push_result.get("exit_code", 0) != 0:
                raise _shell_error("git push", push_result)

        # Rekey the workspace mirror directory so future calls using `ref=new_branch`
        # see the same working tree (including any uncommitted edits).
        effective_new = _tw()._effective_ref_for_repo(full_name, new_branch)
        new_repo_dir = _workspace_path(full_name, effective_new)
        moved = False
        if os.path.abspath(new_repo_dir) != os.path.abspath(repo_dir):
            if os.path.exists(new_repo_dir):
                raise GitHubAPIError(
                    f"Workspace mirror already exists for branch {effective_new!r}: {new_repo_dir}"
                )
            os.makedirs(os.path.dirname(new_repo_dir), exist_ok=True)
            shutil.move(repo_dir, new_repo_dir)
            moved = True
        else:
            new_repo_dir = repo_dir

        # Recreate a clean base mirror directory so future operations on the base
        # ref don't accidentally reuse the new branch working copy.
        base_repo_dir = await deps["clone_repo"](
            full_name, ref=effective_base, preserve_changes=False
        )

        return {
            "base_ref": effective_base,
            "new_branch": new_branch,
            "new_repo_dir": new_repo_dir,
            "base_repo_dir": base_repo_dir,
            "moved_workspace": moved,
            "checkout": _slim_shell_result(checkout),
            "push": _slim_shell_result(push_result) if push_result is not None else None,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_create_branch")


@mcp_tool(write_action=True)
async def workspace_delete_branch(
    full_name: str | None = None,
    branch: str = "",
    *,
    owner: str | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    """Delete a non-default branch using the repo mirror (workspace clone).

    This is the workspace counterpart to branch-creation helpers and is intended
    for closing out ephemeral feature branches once their work has been merged.
    """

    try:
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        deps = _tw()._workspace_deps()

        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("branch must be a non-empty string")

        branch = branch.strip()

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
            timeout_seconds=t_default,
        )

        # Delete remote first; if the remote delete fails, surface that.
        delete_remote = await deps["run_shell"](
            f"git push origin --delete {shlex.quote(branch)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )
        if delete_remote.get("exit_code", 0) != 0:
            raise _shell_error("git push origin --delete", delete_remote)

        # Then delete local branch if it exists. If it does not, treat that as best-effort.
        delete_local = await deps["run_shell"](
            f"git branch -D {shlex.quote(branch)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )

        return {
            "default_branch": default_branch,
            "deleted_branch": branch,
            "delete_remote": _slim_shell_result(delete_remote),
            "delete_local": _slim_shell_result(delete_local),
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_delete_branch")


@mcp_tool(write_action=True)
async def workspace_self_heal_branch(
    full_name: str | None = None,
    branch: str = "",
    *,
    base_ref: str = "main",
    new_branch: str | None = None,
    discard_uncommitted_changes: bool = True,
    delete_mangled_branch: bool = True,
    reset_base: bool = True,
    enumerate_repo: bool = True,
    dry_run: bool = False,
    owner: str | None = None,
    repo: str | None = None,
) -> dict[str, Any]:
    """Detect a mangled repo mirror branch and recover to a fresh branch.

    This tool targets cases where a repo mirror (workspace clone) becomes inconsistent (wrong
    branch checked out, merge/rebase state, conflicts, etc.). When healing, it:

    1) Diagnoses the repo mirror for ``branch``.
    2) Optionally deletes the mangled branch (remote + best-effort local).
    3) Resets the base branch repo mirror (default: ``main``).
    4) Creates + pushes a new fresh branch.
    5) Ensures a clean repo mirror for the new branch.
    6) Optionally returns a small repo snapshot to rebuild context.

    Returns plain-language step logs for UI rendering.
    """

    try:
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        deps = _tw()._workspace_deps()

        if not isinstance(branch, str) or not branch.strip():
            raise ValueError("branch must be a non-empty string")
        branch = branch.strip()

        effective_base = _tw()._effective_ref_for_repo(full_name, base_ref)
        steps: list[dict[str, Any]] = []

        def step(action: str, detail: str, *, status: str = "ok", **extra: Any) -> None:
            payload: dict[str, Any] = {
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
                "Uncommitted changes detected in the repo mirror; set discard_uncommitted_changes=true to proceed."
            )

        if dry_run:
            step(
                "Dry run",
                "Detected a mangled repo mirror; would delete/reset/recreate a branch, but dry_run=true.",
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

        # Remove the local repo mirror dir for the mangled branch (forces a clean re-clone later).
        mangled_workspace_dir = _tw()._workspace_path(
            full_name, _tw()._effective_ref_for_repo(full_name, branch)
        )
        if os.path.isdir(mangled_workspace_dir):
            shutil.rmtree(mangled_workspace_dir)
            step(
                "Remove local repo mirror",
                f"Deleted local repo mirror directory for '{branch}'.",
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

        # Reset base branch repo mirror.
        if reset_base:
            base_repo_dir = await deps["clone_repo"](
                full_name, ref=effective_base, preserve_changes=False
            )
            step(
                "Reset base",
                f"Reset local repo mirror for base ref '{effective_base}'.",
                repo_dir=base_repo_dir,
            )
        else:
            base_repo_dir = await deps["clone_repo"](
                full_name, ref=effective_base, preserve_changes=True
            )
            step(
                "Base ready",
                f"Using existing base repo mirror for '{effective_base}' without resetting.",
                repo_dir=base_repo_dir,
            )

        # Create a fresh branch.
        if new_branch:
            candidate = new_branch
        else:
            candidate = f"heal/{_safe_branch_slug(branch)}-{_tw().uuid.uuid4().hex}"
        candidate = _safe_branch_slug(candidate)

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
            timeout_seconds=t_default,
        )
        await _run_shell_ok(
            deps,
            f"git checkout -b {shlex.quote(candidate)}",
            cwd=base_repo_dir,
            timeout_seconds=t_default,
        )
        await _run_shell_ok(
            deps,
            f"git push -u origin {shlex.quote(candidate)}",
            cwd=base_repo_dir,
            timeout_seconds=t_default,
        )

        # The freshly checked out local repo mirror is used for the new branch.
        new_repo_dir = base_repo_dir
        step(
            "Fresh repo mirror ready",
            f"Created a clean repo mirror for '{candidate}'.",
            repo_dir=new_repo_dir,
        )

        snapshot: dict[str, Any] = {}
        if enumerate_repo:
            log_res = await deps["run_shell"](
                "git log -n 1 --oneline", cwd=new_repo_dir, timeout_seconds=t_default
            )
            st_res = await deps["run_shell"](
                "git status --porcelain", cwd=new_repo_dir, timeout_seconds=t_default
            )

            # Top-level entries (trim to keep responses small).
            try:
                entries = [
                    e for e in sorted(os.listdir(new_repo_dir)) if e not in {".git", ".venv-mcp"}
                ]
            except Exception:
                entries = []

            # Count files excluding .git and .venv-mcp.
            file_count = 0
            for _root, dirs, files in os.walk(new_repo_dir):
                dirs[:] = [d for d in dirs if d not in {".git", ".venv-mcp"}]
                file_count += len(files)

            snapshot = {
                "head": (log_res.get("stdout", "") or "").strip() or None,
                "clean": not (st_res.get("stdout", "") or "").strip(),
                "top_level": entries,
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
    full_name: str | None = None,
    ref: str = "main",
    *,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Report how a repo mirror (workspace clone) differs from its remote branch."""
    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
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
    full_name: str | None = None,
    ref: str = "main",
    *,
    discard_local_changes: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Reset a repo mirror (workspace clone) to match the remote branch."""
    try:
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        before = await _workspace_sync_snapshot(deps, repo_dir=repo_dir, branch=effective_ref)

        if (not discard_local_changes) and (not before["is_clean"] or before["ahead"] > 0):
            raise GitHubAPIError(
                "Repo mirror has local changes or unpushed commits. "
                "Re-run with discard_local_changes=true to force sync."
            )

        await _run_shell_ok(
            deps,
            f"git reset --hard {shlex.quote(before['remote_ref'])}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )
        if discard_local_changes:
            await _run_shell_ok(
                deps,
                "git clean -fd",
                cwd=repo_dir,
                timeout_seconds=t_default,
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


@mcp_tool(write_action=True)
async def workspace_sync_bidirectional(
    full_name: str | None = None,
    ref: str = "main",
    commit_message: str = "Sync workspace changes",
    add_all: bool = True,
    push: bool = True,
    *,
    discard_local_changes: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Sync repo mirror changes to the remote and refresh local state from GitHub."""
    try:
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        actions: list[str] = []
        before = await _workspace_sync_snapshot(deps, repo_dir=repo_dir, branch=effective_ref)
        snapshot = before

        if snapshot["behind"] > 0:
            if snapshot["ahead"] > 0:
                if not discard_local_changes:
                    raise GitHubAPIError(
                        "Repo mirror and remote have diverged. "
                        "Re-run with discard_local_changes=true to reset to remote."
                    )
                actions.append("reset_diverged_to_remote")
            elif not snapshot["is_clean"]:
                if not discard_local_changes:
                    raise GitHubAPIError(
                        "Repo mirror is behind remote and has local changes. "
                        "Commit local changes or re-run with discard_local_changes=true."
                    )
                actions.append("discard_local_changes")
            else:
                actions.append("fast_forward_from_remote")

            await _run_shell_ok(
                deps,
                f"git reset --hard {shlex.quote(snapshot['remote_ref'])}",
                cwd=repo_dir,
                timeout_seconds=t_default,
            )
            if discard_local_changes:
                await _run_shell_ok(
                    deps,
                    "git clean -fd",
                    cwd=repo_dir,
                    timeout_seconds=t_default,
                )
            snapshot = await _workspace_sync_snapshot(deps, repo_dir=repo_dir, branch=effective_ref)

        if not snapshot["is_clean"]:
            if add_all:
                add_result = await deps["run_shell"](
                    "git add -A", cwd=repo_dir, timeout_seconds=t_default
                )
                if add_result.get("exit_code", 0) != 0:
                    raise _shell_error("git add -A", add_result)

            status_result = await deps["run_shell"](
                "git status --porcelain", cwd=repo_dir, timeout_seconds=t_default
            )
            status_lines = (status_result.get("stdout", "") or "").strip().splitlines()
            if status_lines:
                commit_cmd = f"git commit -m {shlex.quote(commit_message)}"
                commit_result = await deps["run_shell"](
                    commit_cmd, cwd=repo_dir, timeout_seconds=t_default
                )
                if commit_result.get("exit_code", 0) != 0:
                    raise _shell_error("git commit", commit_result)
                actions.append("committed_local_changes")

            snapshot = await _workspace_sync_snapshot(deps, repo_dir=repo_dir, branch=effective_ref)

        if push and snapshot["ahead"] > 0:
            push_cmd = f"git push origin HEAD:{effective_ref}"
            push_result = await deps["run_shell"](push_cmd, cwd=repo_dir, timeout_seconds=t_default)
            if push_result.get("exit_code", 0) != 0:
                raise _shell_error("git push", push_result)
            actions.append("pushed_to_remote")
            snapshot = await _workspace_sync_snapshot(deps, repo_dir=repo_dir, branch=effective_ref)

        return {
            "branch": effective_ref,
            "full_name": full_name,
            "repo_dir": repo_dir,
            "discard_local_changes": discard_local_changes,
            "actions": actions,
            "before": before,
            "after": snapshot,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_sync_bidirectional")
