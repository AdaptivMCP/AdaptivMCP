# Split from github_mcp.tools_workspace (generated).
"""Workspace git porcelain helpers.

These tools exist to make common git operations ergonomic for MCP clients
operating against the persistent repo mirror ("workspace clone").

Why these wrappers exist (instead of asking clients to run arbitrary git
commands):
- they normalize repo/ref selection via the same logic as the other workspace
  tools.
- they inject git auth automatically via ``_workspace_deps``.
- they return structured, JSON-serializable payloads that are easier to render
  in UI clients.
"""

from __future__ import annotations

import shlex
from typing import Any

from github_mcp import config
from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import _structured_tool_error, mcp_tool
from github_mcp.utils import _normalize_timeout_seconds

from ._shared import _resolve_full_name, _resolve_ref, _tw


def _split_status_lines(text: str) -> list[str]:
    return [ln for ln in (text or "").splitlines() if ln.strip()]


def _parse_porcelain_v1(lines: list[str]) -> dict[str, Any]:
    """Parse `git status --porcelain=v1 --branch` output."""

    branch_line: str | None = None
    if lines and lines[0].startswith("##"):
        branch_line = lines.pop(0)

    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []

    for ln in lines:
        if ln.startswith("?? "):
            untracked.append(ln[3:].strip())
            continue
        if len(ln) < 4:
            continue
        idx = ln[0]
        wtree = ln[1]
        path = ln[3:].strip()
        if idx != " ":
            staged.append(path)
        if wtree != " ":
            unstaged.append(path)

    return {
        "branch": (branch_line or "").strip() or None,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "is_clean": not (staged or unstaged or untracked),
    }


@mcp_tool(write_action=False)
async def workspace_git_status(
    full_name: str | None = None,
    *,
    ref: str = "main",
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Return a structured git status for the workspace mirror."""

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        # Ensure checkout is consistent.
        await deps["run_shell"](
            f"git checkout {shlex.quote(effective_ref)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )

        res = await deps["run_shell"](
            "git status --porcelain=v1 --branch",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git status failed: {stderr}")

        parsed = _parse_porcelain_v1(_split_status_lines(res.get("stdout", "") or ""))
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "raw": (res.get("stdout", "") or "").strip(),
            **parsed,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_status")


@mcp_tool(write_action=True)
async def workspace_git_stage(
    full_name: str | None = None,
    *,
    ref: str = "main",
    paths: list[str] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Stage changes in the workspace mirror.

    When `paths` is omitted (None), stages all changes (`git add -A`).
    """

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        if paths is None:
            cmd = "git add -A"
        else:
            quoted = " ".join(shlex.quote(p) for p in paths if isinstance(p, str) and p.strip())
            cmd = f"git add -- {quoted}" if quoted else "git add -A"

        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git add failed: {stderr}")

        staged = await deps["run_shell"](
            "git diff --cached --name-only",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )
        staged_files = [
            ln.strip() for ln in (staged.get("stdout", "") or "").splitlines() if ln.strip()
        ]

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "command": cmd,
            "staged_files": staged_files,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_stage")


@mcp_tool(write_action=True)
async def workspace_git_unstage(
    full_name: str | None = None,
    *,
    ref: str = "main",
    paths: list[str] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Unstage changes in the workspace mirror (keeps working tree edits)."""

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        if not paths:
            cmd = "git reset"
        else:
            quoted = " ".join(shlex.quote(p) for p in paths if isinstance(p, str) and p.strip())
            cmd = f"git reset -- {quoted}" if quoted else "git reset"

        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git reset failed: {stderr}")

        staged = await deps["run_shell"](
            "git diff --cached --name-only",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )
        staged_files = [
            ln.strip() for ln in (staged.get("stdout", "") or "").splitlines() if ln.strip()
        ]

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "command": cmd,
            "staged_files": staged_files,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_unstage")


@mcp_tool(write_action=True)
async def workspace_git_pull(
    full_name: str | None = None,
    *,
    ref: str = "main",
    strategy: str = "ff-only",
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Pull remote changes into the workspace mirror.

    strategy:
    - "ff-only" (default): refuse merge commits.
    - "merge": allow merge commits.
    - "rebase": rebase local commits on top of remote.
    """

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        allowed = {"ff-only", "merge", "rebase"}
        if strategy not in allowed:
            raise ValueError(f"strategy must be one of {sorted(allowed)}")

        await deps["run_shell"](
            f"git checkout {shlex.quote(effective_ref)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )

        fetch = await deps["run_shell"](
            "git fetch --prune origin",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )
        if fetch.get("exit_code", 0) != 0:
            stderr = fetch.get("stderr", "") or fetch.get("stdout", "")
            raise GitHubAPIError(f"git fetch failed: {stderr}")

        if strategy == "ff-only":
            pull_cmd = f"git pull --ff-only origin {shlex.quote(effective_ref)}"
        elif strategy == "rebase":
            pull_cmd = f"git pull --rebase origin {shlex.quote(effective_ref)}"
        else:
            pull_cmd = f"git pull origin {shlex.quote(effective_ref)}"

        pull = await deps["run_shell"](pull_cmd, cwd=repo_dir, timeout_seconds=t_default)
        if pull.get("exit_code", 0) != 0:
            stderr = pull.get("stderr", "") or pull.get("stdout", "")
            raise GitHubAPIError(f"git pull failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "strategy": strategy,
            "fetch": {
                "exit_code": fetch.get("exit_code"),
                "stdout": fetch.get("stdout"),
                "stderr": fetch.get("stderr"),
            },
            "pull": {
                "exit_code": pull.get("exit_code"),
                "stdout": pull.get("stdout"),
                "stderr": pull.get("stderr"),
            },
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_pull")


@mcp_tool(write_action=True)
async def workspace_git_push(
    full_name: str | None = None,
    *,
    ref: str = "main",
    set_upstream: bool = True,
    force_with_lease: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Push the workspace mirror branch to origin."""

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        await deps["run_shell"](
            f"git checkout {shlex.quote(effective_ref)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )

        flags: list[str] = []
        if set_upstream:
            flags.append("-u")
        if force_with_lease:
            flags.append("--force-with-lease")
        flag_str = " ".join(flags)
        push_cmd = f"git push {flag_str} origin HEAD".strip()

        push = await deps["run_shell"](push_cmd, cwd=repo_dir, timeout_seconds=t_default)
        if push.get("exit_code", 0) != 0:
            stderr = push.get("stderr", "") or push.get("stdout", "")
            raise GitHubAPIError(f"git push failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "command": push_cmd,
            "push": {
                "exit_code": push.get("exit_code"),
                "stdout": push.get("stdout"),
                "stderr": push.get("stderr"),
            },
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_push")


@mcp_tool(write_action=True)
async def workspace_open_pr_from_workspace(
    full_name: str,
    *,
    ref: str = "main",
    base: str = "main",
    title: str | None = None,
    body: str | None = None,
    draft: bool = False,
) -> dict[str, Any]:
    """Open (or reuse) a PR for the workspace branch into `base`."""

    from github_mcp.main_tools.pull_requests import open_pr_for_existing_branch

    try:
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        return await open_pr_for_existing_branch(
            full_name=full_name,
            branch=effective_ref,
            base=base,
            title=title,
            body=body,
            draft=draft,
        )
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_open_pr_from_workspace")
