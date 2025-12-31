# Split from github_mcp.tools_workspace (generated).
import shlex
from typing import Any, Dict, List, Optional

import github_mcp.config as config
from github_mcp.diff_utils import colorize_unified_diff, diff_stats, truncate_diff

from github_mcp.exceptions import GitHubAPIError
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw
    return tw

def _slim_shell_result(result: Any, *, max_chars: int = 0) -> Dict[str, Any]:
    """Return a connector-safe view of a run_shell result.

    Set max_chars to 0 (or a negative value) to disable truncation.
    """
    if not isinstance(result, dict):
        raw = str(result)
        if max_chars and max_chars > 0:
            raw = raw[:max_chars]
        return {"raw": raw}
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()

    if max_chars and max_chars > 0:
        out_stdout = stdout[:max_chars] if stdout else ""
        out_stderr = stderr[:max_chars] if stderr else ""
        stdout_truncated = len(stdout) > max_chars
        stderr_truncated = len(stderr) > max_chars
    else:
        out_stdout = stdout
        out_stderr = stderr
        stdout_truncated = False
        stderr_truncated = False

    return {
        "exit_code": result.get("exit_code"),
        "timed_out": result.get("timed_out", False),
        "stdout": out_stdout,
        "stderr": out_stderr,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


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
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        deps = _tw()._workspace_deps()
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        if add_all:
            add_result = await deps["run_shell"]("git add -A", cwd=repo_dir, timeout_seconds=120)
            if add_result["exit_code"] != 0:
                stderr = add_result.get("stderr", "") or add_result.get("stdout", "")
                raise GitHubAPIError(f"git add failed: {stderr}")

        status_result = await deps["run_shell"](
            "git status --porcelain", cwd=repo_dir, timeout_seconds=60
        )

        diff_before_commit = await deps["run_shell"](
            "git diff --cached --no-color", cwd=repo_dir, timeout_seconds=120
        )
        diff_text = (diff_before_commit.get("stdout", "") if isinstance(diff_before_commit, dict) else "")
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

        # Keep tool responses small to avoid connector transport issues.
        rev = await deps["run_shell"]("git rev-parse HEAD", cwd=repo_dir, timeout_seconds=60)
        head_sha = (rev.get("stdout", "").strip() if isinstance(rev, dict) else "")
        oneline = await deps["run_shell"]("git log -1 --oneline", cwd=repo_dir, timeout_seconds=60)
        head_summary = (oneline.get("stdout", "").strip() if isinstance(oneline, dict) else "")

        try:
            stats = diff_stats(diff_text)
            config.TOOLS_LOGGER.chat(
                "Committed workspace changes (%s files) (+%s -%s)",
                len(status_lines),
                stats.added,
                stats.removed,
                extra={"repo": full_name, "ref": effective_ref, "event": "workspace_commit_diff_summary"},
            )

            if config.TOOLS_LOGGER.isEnabledFor(config.DETAILED_LEVEL) and diff_text.strip():
                truncated = truncate_diff(
                    diff_text,
                    max_lines=config.WRITE_DIFF_LOG_MAX_LINES,
                    max_chars=config.WRITE_DIFF_LOG_MAX_CHARS,
                )
                colored = colorize_unified_diff(truncated)
                config.TOOLS_LOGGER.detailed(
                    "Workspace commit diff\n%s",
                    colored,
                    extra={"repo": full_name, "ref": effective_ref, "event": "workspace_commit_diff"},
                )
        except Exception:
            pass

        return {
            "branch": effective_ref,
            "changed_files": (status_lines if config.WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS <= 0 else status_lines[: config.WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS]),
            "changed_files_truncated": (config.WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS > 0 and len(status_lines) > config.WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS),
            "commit_sha": head_sha,
            "commit_summary": head_summary,
            "commit": _slim_shell_result(commit_result, max_chars=config.WORKSPACE_SHELL_RESULT_MAX_CHARS),
            "push": _slim_shell_result(push_result, max_chars=config.WORKSPACE_SHELL_RESULT_MAX_CHARS) if push_result is not None else None,
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
        full_name = _tw()._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = _tw()._resolve_ref(ref, branch=branch)
        effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
        deps = _tw()._workspace_deps()
        repo_dir = await deps["clone_repo"](full_name, ref=effective_ref, preserve_changes=True)

        add_cmd = "git add -- " + " ".join(shlex.quote(path) for path in files)
        add_result = await deps["run_shell"](add_cmd, cwd=repo_dir, timeout_seconds=120)
        if add_result["exit_code"] != 0:
            stderr = add_result.get("stderr", "") or add_result.get("stdout", "")
            raise GitHubAPIError(f"git add failed: {stderr}")

        staged_files_result = await deps["run_shell"](
            "git diff --cached --name-only", cwd=repo_dir, timeout_seconds=60
        )

        diff_before_commit_files = await deps["run_shell"](
            "git diff --cached --no-color", cwd=repo_dir, timeout_seconds=120
        )
        diff_text_files = (diff_before_commit_files.get("stdout", "") if isinstance(diff_before_commit_files, dict) else "")
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

        # Keep tool responses small to avoid connector transport issues.
        rev = await deps["run_shell"]("git rev-parse HEAD", cwd=repo_dir, timeout_seconds=60)
        head_sha = (rev.get("stdout", "").strip() if isinstance(rev, dict) else "")
        oneline = await deps["run_shell"]("git log -1 --oneline", cwd=repo_dir, timeout_seconds=60)
        head_summary = (oneline.get("stdout", "").strip() if isinstance(oneline, dict) else "")

        try:
            stats = diff_stats(diff_text_files)
            config.TOOLS_LOGGER.chat(
                "Committed selected workspace changes (%s files) (+%s -%s)",
                len(staged_files),
                stats.added,
                stats.removed,
                extra={"repo": full_name, "ref": effective_ref, "event": "workspace_commit_diff_summary"},
            )

            if config.TOOLS_LOGGER.isEnabledFor(config.DETAILED_LEVEL) and diff_text_files.strip():
                truncated = truncate_diff(
                    diff_text_files,
                    max_lines=config.WRITE_DIFF_LOG_MAX_LINES,
                    max_chars=config.WRITE_DIFF_LOG_MAX_CHARS,
                )
                colored = colorize_unified_diff(truncated)
                config.TOOLS_LOGGER.detailed(
                    "Workspace commit diff\n%s",
                    colored,
                    extra={"repo": full_name, "ref": effective_ref, "event": "workspace_commit_diff"},
                )
        except Exception:
            pass


        return {
            "branch": effective_ref,
            "staged_files": (staged_files if config.WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS <= 0 else staged_files[: config.WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS]),
            "staged_files_truncated": (config.WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS > 0 and len(staged_files) > config.WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS),
            "commit_sha": head_sha,
            "commit_summary": head_summary,
            "commit": _slim_shell_result(commit_result, max_chars=config.WORKSPACE_SHELL_RESULT_MAX_CHARS),
            "push": _slim_shell_result(push_result, max_chars=config.WORKSPACE_SHELL_RESULT_MAX_CHARS) if push_result is not None else None,
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

    deps = _tw()._workspace_deps()
    effective_ref = _tw()._effective_ref_for_repo(full_name, ref)
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
