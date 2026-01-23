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

import os
import shlex
import shutil
from typing import Any

from github_mcp import config
from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import _structured_tool_error, mcp_tool
from github_mcp.utils import _normalize_timeout_seconds
from github_mcp.workspace import _workspace_path

from ._shared import _resolve_full_name, _resolve_ref, _tw


def _split_status_lines(text: str) -> list[str]:
    return [ln for ln in (text or "").splitlines() if ln.strip()]


def _clip_text(text: str, *, max_chars: int) -> tuple[str, bool]:
    """Clip a potentially large stdout/stderr string.

    This mirrors the general "bounded outputs" philosophy of the workspace
    tools to keep MCP payloads stable.
    """

    raw = text or ""
    if max_chars <= 0 or len(raw) <= max_chars:
        return (raw, False)
    if max_chars < 4:
        return (raw[: max(0, max_chars)], True)
    return (raw[: max(0, max_chars - 1)] + "…", True)


def _parse_tabbed_rows(lines: list[str], *, expected_cols: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for ln in lines:
        if not ln:
            continue
        parts = ln.split("\t")
        if len(parts) < expected_cols:
            continue
        # Preserve extra tabs in the last field.
        head = parts[: expected_cols - 1]
        tail = ["\t".join(parts[expected_cols - 1 :])]
        rows.append(head + tail)
    return rows


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


@mcp_tool(write_action=False)
async def workspace_git_log(
    full_name: str | None = None,
    *,
    ref: str = "main",
    rev_range: str = "HEAD",
    max_entries: int = 50,
    paths: list[str] | None = None,
    max_chars: int = 120000,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Return recent commits from the workspace mirror.

    Notes:
    - `rev_range` can be any git revision range expression (e.g. "HEAD", "main..HEAD").
    - When `paths` is provided, the log is limited to those paths.
    """

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        n = int(max_entries)
        if n <= 0:
            n = 1
        if n > 500:
            n = 500

        await deps["run_shell"](
            f"git checkout {shlex.quote(effective_ref)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )

        cmd_parts = [
            "git",
            "log",
            "-n",
            str(n),
            "--date=iso-strict",
            "--pretty=format:%H%x09%an%x09%ad%x09%s",
            rev_range,
        ]
        if paths:
            clean = [p for p in paths if isinstance(p, str) and p.strip()]
            if clean:
                cmd_parts.append("--")
                cmd_parts.extend(clean)
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git log failed: {stderr}")

        out_raw, truncated = _clip_text(
            (res.get("stdout", "") or "").rstrip("\n"), max_chars=max_chars
        )
        rows = _parse_tabbed_rows(out_raw.splitlines(), expected_cols=4)
        commits = [{"sha": r[0], "author": r[1], "date": r[2], "subject": r[3]} for r in rows]

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "rev_range": rev_range,
            "paths": paths or [],
            "command": cmd,
            "commits": commits,
            "raw": out_raw,
            "truncated": truncated,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_log")


@mcp_tool(write_action=False)
async def workspace_git_show(
    full_name: str | None = None,
    *,
    ref: str = "main",
    git_ref: str = "HEAD",
    include_patch: bool = True,
    paths: list[str] | None = None,
    max_chars: int = 200000,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Show a commit (or any git object) from the workspace mirror."""

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

        cmd_parts = ["git", "show", "--date=iso-strict", "--pretty=fuller"]
        if not include_patch:
            cmd_parts.extend(["--name-status", "--no-patch"])
        cmd_parts.append(git_ref)
        if paths:
            clean = [p for p in paths if isinstance(p, str) and p.strip()]
            if clean:
                cmd_parts.append("--")
                cmd_parts.extend(clean)
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git show failed: {stderr}")

        out_raw, truncated = _clip_text(
            (res.get("stdout", "") or "").rstrip("\n"), max_chars=max_chars
        )
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "git_ref": git_ref,
            "include_patch": include_patch,
            "paths": paths or [],
            "command": cmd,
            "output": out_raw,
            "truncated": truncated,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_show")


@mcp_tool(write_action=False)
async def workspace_git_blame(
    full_name: str | None = None,
    *,
    ref: str = "main",
    path: str = "",
    git_ref: str = "HEAD",
    start_line: int = 1,
    end_line: int | None = None,
    max_lines: int = 200,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Return `git blame` output for a file range.

    This tool returns the human-friendly blame lines (not porcelain) so it can
    be used quickly for debugging.
    """

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        if not isinstance(path, str) or not path.strip():
            raise ValueError("path is required")

        s = int(start_line)
        if s <= 0:
            s = 1

        if end_line is None:
            e = s + max(1, int(max_lines)) - 1
        else:
            e = int(end_line)
        if e < s:
            e = s
        # Keep payloads bounded.
        if e - s + 1 > 2000:
            e = s + 2000 - 1

        await deps["run_shell"](
            f"git checkout {shlex.quote(effective_ref)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )

        cmd = (
            "git blame --date=iso-strict "
            + f"-L {s},{e} {shlex.quote(git_ref)} -- {shlex.quote(path)}"
        )
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git blame failed: {stderr}")

        lines = [ln.rstrip("\n") for ln in (res.get("stdout", "") or "").splitlines() if ln.strip()]
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "git_ref": git_ref,
            "path": path,
            "start_line": s,
            "end_line": e,
            "command": cmd,
            "lines": lines,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_blame")


@mcp_tool(write_action=False)
async def workspace_git_branches(
    full_name: str | None = None,
    *,
    ref: str = "main",
    include_remote: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """List branches available in the workspace mirror."""

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

        refs = ["refs/heads"]
        if include_remote:
            refs.append("refs/remotes/origin")

        fmt = "%(_refname)\t%(refname:short)\t%(objectname)\t%(upstream:short)\t%(upstream:track)\t%(HEAD)"
        # Use a stable format line; git treats percent-parens as placeholders.
        cmd = (
            "git for-each-ref --format="
            + shlex.quote(fmt)
            + " "
            + " ".join(shlex.quote(r) for r in refs)
        )
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git for-each-ref failed: {stderr}")

        lines = [ln.strip() for ln in (res.get("stdout", "") or "").splitlines() if ln.strip()]
        rows = _parse_tabbed_rows(lines, expected_cols=6)
        branches_out = [
            {
                "refname": r[0],
                "name": r[1],
                "sha": r[2],
                "upstream": r[3] or None,
                "upstream_track": r[4] or None,
                "is_head": (r[5] or "").strip() == "*",
            }
            for r in rows
        ]
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "include_remote": include_remote,
            "command": cmd,
            "branches": branches_out,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_branches")


@mcp_tool(write_action=False)
async def workspace_git_tags(
    full_name: str | None = None,
    *,
    ref: str = "main",
    max_entries: int = 200,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """List tags in the workspace mirror (most recent first when possible)."""

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

        n = int(max_entries)
        if n <= 0:
            n = 1
        if n > 2000:
            n = 2000

        fmt = "%(refname:strip=2)\t%(objectname)\t%(creatordate:iso-strict)"
        cmd = "git tag -l --sort=-creatordate --format=" + shlex.quote(fmt) + f" | head -n {n}"
        # `head` is a small portability risk, but the server already relies on
        # common shell tools. If `head` is unavailable, git output will still
        # be bounded by the MCP response shaping.
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git tag failed: {stderr}")

        lines = [ln.strip() for ln in (res.get("stdout", "") or "").splitlines() if ln.strip()]
        rows = _parse_tabbed_rows(lines, expected_cols=3)
        tags = [{"name": r[0], "sha": r[1], "date": r[2] or None} for r in rows]
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "max_entries": n,
            "command": cmd,
            "tags": tags,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_tags")


@mcp_tool(write_action=False)
async def workspace_git_stash_list(
    full_name: str | None = None,
    *,
    ref: str = "main",
    max_entries: int = 50,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """List stashes in the workspace mirror."""

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

        n = int(max_entries)
        if n <= 0:
            n = 1
        if n > 500:
            n = 500

        cmd = f"git stash list --date=iso-strict | head -n {n}"
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git stash list failed: {stderr}")

        stashes: list[dict[str, Any]] = []
        for ln in (res.get("stdout", "") or "").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            # Example: "stash@{0}: On main: wip"
            if ":" in ln:
                stash_ref, rest = ln.split(":", 1)
                stashes.append({"ref": stash_ref.strip(), "description": rest.strip()})
            else:
                stashes.append({"ref": None, "description": ln})

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "max_entries": n,
            "command": cmd,
            "stashes": stashes,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_stash_list")


@mcp_tool(write_action=True)
async def workspace_git_stash_save(
    full_name: str | None = None,
    *,
    ref: str = "main",
    message: str | None = None,
    include_untracked: bool = False,
    keep_index: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Create a stash in the workspace mirror (git stash push)."""

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
        if include_untracked:
            flags.append("-u")
        if keep_index:
            flags.append("--keep-index")
        if isinstance(message, str) and message.strip():
            flags.extend(["-m", message.strip()])

        cmd_parts = ["git", "stash", "push"] + flags
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git stash push failed: {stderr}")

        stdout = (res.get("stdout", "") or "").strip()
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "command": cmd,
            "stdout": stdout,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_stash_save")


async def _workspace_git_stash_apply_like(
    *,
    action: str,
    full_name: str,
    effective_ref: str,
    repo_dir: str,
    deps: dict[str, Any],
    t_default: float,
    stash_ref: str,
) -> dict[str, Any]:
    cmd = f"git stash {action} {shlex.quote(stash_ref)}".strip()
    res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
    if res.get("exit_code", 0) != 0:
        stderr = res.get("stderr", "") or res.get("stdout", "")
        raise GitHubAPIError(f"git stash {action} failed: {stderr}")
    return {
        "full_name": full_name,
        "ref": effective_ref,
        "stash_ref": stash_ref,
        "command": cmd,
        "stdout": (res.get("stdout", "") or "").strip(),
        "stderr": (res.get("stderr", "") or "").strip(),
        "ok": True,
    }


@mcp_tool(write_action=True)
async def workspace_git_stash_pop(
    full_name: str | None = None,
    *,
    ref: str = "main",
    stash_ref: str = "stash@{0}",
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Pop a stash in the workspace mirror (git stash pop)."""

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
        return await _workspace_git_stash_apply_like(
            action="pop",
            full_name=full_name,
            effective_ref=effective_ref,
            repo_dir=repo_dir,
            deps=deps,
            t_default=t_default,
            stash_ref=stash_ref,
        )
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_stash_pop")


@mcp_tool(write_action=True)
async def workspace_git_stash_apply(
    full_name: str | None = None,
    *,
    ref: str = "main",
    stash_ref: str = "stash@{0}",
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Apply a stash in the workspace mirror (git stash apply)."""

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
        return await _workspace_git_stash_apply_like(
            action="apply",
            full_name=full_name,
            effective_ref=effective_ref,
            repo_dir=repo_dir,
            deps=deps,
            t_default=t_default,
            stash_ref=stash_ref,
        )
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_stash_apply")


@mcp_tool(write_action=True)
async def workspace_git_stash_drop(
    full_name: str | None = None,
    *,
    ref: str = "main",
    stash_ref: str = "stash@{0}",
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Drop a stash in the workspace mirror (git stash drop)."""

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
        return await _workspace_git_stash_apply_like(
            action="drop",
            full_name=full_name,
            effective_ref=effective_ref,
            repo_dir=repo_dir,
            deps=deps,
            t_default=t_default,
            stash_ref=stash_ref,
        )
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_stash_drop")


@mcp_tool(write_action=True)
async def workspace_git_checkout(
    full_name: str | None = None,
    *,
    ref: str = "main",
    target: str = "",
    create: bool = False,
    start_point: str | None = None,
    push: bool = False,
    force: bool = False,
    rekey_workspace: bool = True,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Checkout a branch/ref in the workspace mirror.

    Important: workspace clones are keyed by `ref`. If you checkout a different
    branch inside the current mirror directory, subsequent calls using
    `ref=<new-branch>` would otherwise operate on a different directory. When
    `rekey_workspace=true` (default) this tool moves the working copy directory
    to the new branch mirror path so future calls see a consistent worktree.

    - If `create=true`, creates a new local branch (and optionally pushes).
    - `target` must be a non-empty ref name.
    """

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        if not isinstance(target, str) or not target.strip():
            raise ValueError("target must be a non-empty string")
        target = target.strip()
        if ".." in target or "@{" in target:
            raise ValueError("target contains invalid ref sequence")

        await deps["run_shell"](
            f"git checkout {shlex.quote(effective_ref)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )

        flags: list[str] = []
        if force:
            flags.append("-f")

        if create:
            cmd_parts = ["git", "checkout", *flags, "-b", target]
            if start_point and isinstance(start_point, str) and start_point.strip():
                cmd_parts.append(start_point.strip())
        else:
            cmd_parts = ["git", "checkout", *flags, target]

        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        checkout = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if checkout.get("exit_code", 0) != 0:
            stderr = checkout.get("stderr", "") or checkout.get("stdout", "")
            raise GitHubAPIError(f"git checkout failed: {stderr}")

        push_res = None
        if push:
            push_cmd = f"git push -u origin {shlex.quote(target)}"
            push_res = await deps["run_shell"](push_cmd, cwd=repo_dir, timeout_seconds=t_default)
            if push_res.get("exit_code", 0) != 0:
                stderr = push_res.get("stderr", "") or push_res.get("stdout", "")
                raise GitHubAPIError(f"git push failed: {stderr}")

        effective_target = _tw()._effective_ref_for_repo(full_name, target)
        moved = False
        new_repo_dir = repo_dir
        refreshed_old_repo_dir = None

        if rekey_workspace and effective_target != effective_ref:
            desired_dir = _workspace_path(full_name, effective_target)
            if os.path.exists(desired_dir):
                raise GitHubAPIError(
                    f"Workspace mirror already exists for target ref {effective_target!r}: {desired_dir}"
                )
            os.makedirs(os.path.dirname(desired_dir), exist_ok=True)
            shutil.move(repo_dir, desired_dir)
            moved = True
            new_repo_dir = desired_dir
            # Recreate original mirror so future calls on the old ref don't
            # accidentally use the new branch working copy.
            refreshed_old_repo_dir = await deps["clone_repo"](
                full_name, ref=effective_ref, preserve_changes=False
            )

        return {
            "full_name": full_name,
            "from_ref": effective_ref,
            "target": target,
            "effective_target": effective_target,
            "create": bool(create),
            "start_point": start_point,
            "push": bool(push),
            "force": bool(force),
            "rekey_workspace": bool(rekey_workspace),
            "moved_workspace": moved,
            "repo_dir": new_repo_dir,
            "refreshed_old_repo_dir": refreshed_old_repo_dir,
            "checkout": {
                "exit_code": checkout.get("exit_code"),
                "stdout": checkout.get("stdout"),
                "stderr": checkout.get("stderr"),
            },
            "push_result": {
                "exit_code": push_res.get("exit_code"),
                "stdout": push_res.get("stdout"),
                "stderr": push_res.get("stderr"),
            }
            if push_res is not None
            else None,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_checkout")


@mcp_tool(write_action=True)
async def workspace_git_commit(
    full_name: str | None = None,
    *,
    ref: str = "main",
    message: str = "",
    stage_all: bool = False,
    amend: bool = False,
    no_edit: bool = False,
    allow_empty: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Create a commit in the workspace mirror."""

    try:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")

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

        add_res = None
        if stage_all:
            add_res = await deps["run_shell"]("git add -A", cwd=repo_dir, timeout_seconds=t_default)
            if add_res.get("exit_code", 0) != 0:
                stderr = add_res.get("stderr", "") or add_res.get("stdout", "")
                raise GitHubAPIError(f"git add failed: {stderr}")

        flags: list[str] = []
        if amend:
            flags.append("--amend")
            if no_edit:
                flags.append("--no-edit")
        if allow_empty:
            flags.append("--allow-empty")

        cmd_parts = ["git", "commit"] + flags + ["-m", message.strip()]
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        commit_res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if commit_res.get("exit_code", 0) != 0:
            stderr = commit_res.get("stderr", "") or commit_res.get("stdout", "")
            raise GitHubAPIError(f"git commit failed: {stderr}")

        head_res = await deps["run_shell"](
            "git rev-parse HEAD", cwd=repo_dir, timeout_seconds=t_default
        )
        sha = (head_res.get("stdout", "") or "").strip() or None

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "message": message.strip(),
            "stage_all": bool(stage_all),
            "amend": bool(amend),
            "no_edit": bool(no_edit),
            "allow_empty": bool(allow_empty),
            "command": cmd,
            "add": {
                "exit_code": add_res.get("exit_code"),
                "stdout": add_res.get("stdout"),
                "stderr": add_res.get("stderr"),
            }
            if add_res is not None
            else None,
            "commit": {
                "exit_code": commit_res.get("exit_code"),
                "stdout": commit_res.get("stdout"),
                "stderr": commit_res.get("stderr"),
            },
            "sha": sha,
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_commit")


@mcp_tool(write_action=True)
async def workspace_git_fetch(
    full_name: str | None = None,
    *,
    ref: str = "main",
    remote: str = "origin",
    prune: bool = True,
    tags: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Fetch remote refs into the workspace mirror."""

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
        if prune:
            flags.append("--prune")
        if tags:
            flags.append("--tags")
        cmd = "git fetch " + " ".join([*flags, remote]).strip()
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git fetch failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "remote": remote,
            "prune": bool(prune),
            "tags": bool(tags),
            "command": cmd,
            "stdout": (res.get("stdout", "") or "").strip(),
            "stderr": (res.get("stderr", "") or "").strip(),
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_fetch")


@mcp_tool(write_action=True)
async def workspace_git_reset(
    full_name: str | None = None,
    *,
    ref: str = "main",
    mode: str = "mixed",
    target: str = "HEAD",
    paths: list[str] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Reset the workspace mirror (git reset)."""

    try:
        allowed = {"soft", "mixed", "hard", "merge", "keep"}
        if mode not in allowed:
            raise ValueError(f"mode must be one of {sorted(allowed)}")

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

        cmd_parts = ["git", "reset", f"--{mode}"]
        if isinstance(target, str) and target.strip():
            cmd_parts.append(target.strip())
        if paths:
            clean = [p for p in paths if isinstance(p, str) and p.strip()]
            if clean:
                cmd_parts.append("--")
                cmd_parts.extend(clean)
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git reset failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "mode": mode,
            "target": target,
            "paths": paths or [],
            "command": cmd,
            "stdout": (res.get("stdout", "") or "").strip(),
            "stderr": (res.get("stderr", "") or "").strip(),
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_reset")


@mcp_tool(write_action=True)
async def workspace_git_clean(
    full_name: str | None = None,
    *,
    ref: str = "main",
    dry_run: bool = True,
    remove_directories: bool = True,
    include_ignored: bool = False,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Clean untracked files from the workspace mirror (git clean)."""

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

        flags = []
        flags.append("-n" if dry_run else "-f")
        if remove_directories:
            flags.append("-d")
        if include_ignored:
            flags.append("-x")
        cmd = "git clean " + " ".join(flags)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git clean failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "dry_run": bool(dry_run),
            "remove_directories": bool(remove_directories),
            "include_ignored": bool(include_ignored),
            "command": cmd,
            "stdout": (res.get("stdout", "") or "").strip(),
            "stderr": (res.get("stderr", "") or "").strip(),
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_clean")


@mcp_tool(write_action=True)
async def workspace_git_restore(
    full_name: str | None = None,
    *,
    ref: str = "main",
    paths: list[str] | None = None,
    source_ref: str | None = None,
    staged: bool = False,
    worktree: bool = True,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Restore files in the workspace mirror (git restore).

    - By default restores working tree from HEAD.
    - If staged=true, affects index; if worktree=true, affects working tree.
    """

    try:
        full_name = _resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _resolve_ref(ref, branch=branch)
        deps = _tw()._workspace_deps()
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)
        t_default = _normalize_timeout_seconds(config.ADAPTIV_MCP_DEFAULT_TIMEOUT_SECONDS, 0)

        if not paths:
            raise ValueError("paths is required")
        clean = [p for p in paths if isinstance(p, str) and p.strip()]
        if not clean:
            raise ValueError("paths must contain at least one non-empty path")

        await deps["run_shell"](
            f"git checkout {shlex.quote(effective_ref)}",
            cwd=repo_dir,
            timeout_seconds=t_default,
        )

        if not worktree and not staged:
            raise ValueError("At least one of staged/worktree must be true")
        cmd_parts = ["git", "restore"]
        if source_ref and isinstance(source_ref, str) and source_ref.strip():
            cmd_parts.extend(["--source", source_ref.strip()])
        if staged:
            cmd_parts.append("--staged")
        if worktree:
            cmd_parts.append("--worktree")
        cmd_parts.append("--")
        cmd_parts.extend(clean)
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git restore failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "paths": clean,
            "source_ref": source_ref,
            "staged": bool(staged),
            "worktree": bool(worktree),
            "command": cmd,
            "stdout": (res.get("stdout", "") or "").strip(),
            "stderr": (res.get("stderr", "") or "").strip(),
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_restore")


@mcp_tool(write_action=True)
async def workspace_git_merge(
    full_name: str | None = None,
    *,
    ref: str = "main",
    target: str = "",
    ff_only: bool = False,
    no_ff: bool = False,
    squash: bool = False,
    message: str | None = None,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Merge a ref into the current workspace branch."""

    try:
        if not isinstance(target, str) or not target.strip():
            raise ValueError("target must be a non-empty string")

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
        if ff_only:
            flags.append("--ff-only")
        if no_ff:
            flags.append("--no-ff")
        if squash:
            flags.append("--squash")
        if message and isinstance(message, str) and message.strip():
            flags.extend(["-m", message.strip()])

        cmd_parts = ["git", "merge"] + flags + [target.strip()]
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git merge failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "target": target.strip(),
            "ff_only": bool(ff_only),
            "no_ff": bool(no_ff),
            "squash": bool(squash),
            "message": message,
            "command": cmd,
            "stdout": (res.get("stdout", "") or "").strip(),
            "stderr": (res.get("stderr", "") or "").strip(),
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_merge")


@mcp_tool(write_action=True)
async def workspace_git_rebase(
    full_name: str | None = None,
    *,
    ref: str = "main",
    action: str = "rebase",
    upstream: str | None = None,
    onto: str | None = None,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Run or control a rebase in the workspace mirror.

    action:
    - rebase (default): starts a rebase; requires upstream.
    - continue / abort / skip: control an in-progress rebase.
    """

    try:
        allowed = {"rebase", "continue", "abort", "skip"}
        if action not in allowed:
            raise ValueError(f"action must be one of {sorted(allowed)}")

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

        if action == "rebase":
            if not upstream or not isinstance(upstream, str) or not upstream.strip():
                raise ValueError("upstream is required when action='rebase'")
            cmd_parts = ["git", "rebase"]
            if onto and isinstance(onto, str) and onto.strip():
                cmd_parts.extend(["--onto", onto.strip()])
            cmd_parts.append(upstream.strip())
        else:
            cmd_parts = ["git", "rebase", f"--{action}"]

        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git rebase {action} failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "action": action,
            "upstream": upstream,
            "onto": onto,
            "command": cmd,
            "stdout": (res.get("stdout", "") or "").strip(),
            "stderr": (res.get("stderr", "") or "").strip(),
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_rebase")


@mcp_tool(write_action=True)
async def workspace_git_cherry_pick(
    full_name: str | None = None,
    *,
    ref: str = "main",
    action: str = "pick",
    commits: list[str] | None = None,
    mainline: int | None = None,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Cherry-pick commits in the workspace mirror."""

    try:
        allowed = {"pick", "continue", "abort", "skip"}
        if action not in allowed:
            raise ValueError(f"action must be one of {sorted(allowed)}")

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

        if action == "pick":
            clean = [c for c in (commits or []) if isinstance(c, str) and c.strip()]
            if not clean:
                raise ValueError("commits is required when action='pick'")
            cmd_parts = ["git", "cherry-pick"]
            if mainline is not None:
                cmd_parts.extend(["-m", str(int(mainline))])
            cmd_parts.extend(clean)
        else:
            cmd_parts = ["git", "cherry-pick", f"--{action}"]

        cmd = " ".join(shlex.quote(p) for p in cmd_parts)
        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git cherry-pick {action} failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "action": action,
            "commits": commits or [],
            "mainline": mainline,
            "command": cmd,
            "stdout": (res.get("stdout", "") or "").strip(),
            "stderr": (res.get("stderr", "") or "").strip(),
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_cherry_pick")


@mcp_tool(write_action=True)
async def workspace_git_revert(
    full_name: str | None = None,
    *,
    ref: str = "main",
    commits: list[str] | None = None,
    no_edit: bool = True,
    mainline: int | None = None,
    owner: str | None = None,
    repo: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Revert commits in the workspace mirror."""

    try:
        clean = [c for c in (commits or []) if isinstance(c, str) and c.strip()]
        if not clean:
            raise ValueError("commits is required")

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

        cmd_parts = ["git", "revert"]
        if no_edit:
            cmd_parts.append("--no-edit")
        if mainline is not None:
            cmd_parts.extend(["-m", str(int(mainline))])
        cmd_parts.extend(clean)
        cmd = " ".join(shlex.quote(p) for p in cmd_parts)

        res = await deps["run_shell"](cmd, cwd=repo_dir, timeout_seconds=t_default)
        if res.get("exit_code", 0) != 0:
            stderr = res.get("stderr", "") or res.get("stdout", "")
            raise GitHubAPIError(f"git revert failed: {stderr}")

        return {
            "full_name": full_name,
            "ref": effective_ref,
            "commits": clean,
            "no_edit": bool(no_edit),
            "mainline": mainline,
            "command": cmd,
            "stdout": (res.get("stdout", "") or "").strip(),
            "stderr": (res.get("stderr", "") or "").strip(),
            "ok": True,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_git_revert")


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
