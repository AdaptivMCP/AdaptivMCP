"""Workspace commit/push tools and session-log appenders.

Workspace-backed tools (clone, run commands, commit, and suites).
"""

# Split from github_mcp.tools_workspace (generated).
import shlex
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import github_mcp.config as config
from github_mcp.diff_utils import colorize_unified_diff, truncate_diff
from github_mcp.exceptions import GitHubAPIError
from github_mcp.session_logs import append_session_log_entry, format_bullets
from github_mcp.server import (
    _structured_tool_error,
    mcp_tool,
)


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


def _slim_shell_result(result: Any, *, max_chars: int = 2000) -> Dict[str, Any]:
    """Return a small, connector-safe view of a run_shell result."""
    if not isinstance(result, dict):
        return {"raw": str(result)[:max_chars]}
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    return {
        "exit_code": result.get("exit_code"),
        "timed_out": result.get("timed_out", False),
        "stdout": stdout[:max_chars] if stdout else "",
        "stderr": stderr[:max_chars] if stderr else "",
        "stdout_truncated": len(stdout) > max_chars,
        "stderr_truncated": len(stderr) > max_chars,
    }


# --- Session log automation ---


def _format_status_summary(lines: List[str], *, max_items: int = 30) -> List[str]:
    """Convert porcelain status lines or raw paths into user-facing bullets."""

    out: List[str] = []
    for raw in lines:
        line = (raw or "").rstrip("\n")
        if not line:
            continue

        label = "Updated"
        path = line.strip()

        # Porcelain: two status chars + space + path
        if len(line) >= 4 and line[2] == " ":
            code = line[:2]
            path = line[3:].strip()
            if code.strip() == "??":
                label = "Added"
            elif "A" in code:
                label = "Added"
            elif "D" in code:
                label = "Deleted"
            elif "R" in code:
                label = "Renamed"
            elif "M" in code:
                label = "Updated"

        if not path or path.startswith("session_logs/"):
            continue

        out.append(f"{label}: {path}")
        if len(out) >= max_items:
            break

    return out


async def _try_get_ci_run_summary(
    full_name: str, branch: str, head_sha: str
) -> Optional[Dict[str, str]]:
    """Best-effort: find the most recent workflow run for a specific SHA."""

    try:
        from github_mcp.main_tools.workflows import list_workflow_runs

        payload = await list_workflow_runs(full_name=full_name, branch=branch, per_page=10, page=1)
        runs_json = payload.get("json") if isinstance(payload, dict) else None
        runs = runs_json.get("workflow_runs") if isinstance(runs_json, dict) else None
        if not isinstance(runs, list):
            return None

        for run in runs:
            if not isinstance(run, dict):
                continue
            if (run.get("head_sha") or "").strip() == head_sha:
                return {
                    "status": str(run.get("status") or ""),
                    "conclusion": str(run.get("conclusion") or ""),
                    "html_url": str(run.get("html_url") or ""),
                }
    except Exception:
        return None

    return None


async def _try_get_render_log_excerpt(head_sha: str, *, max_lines: int = 6) -> Optional[List[str]]:
    """Best-effort: excerpt recent Render logs (requires RENDER_API_KEY)."""

    try:
        from github_mcp.main_tools.render_observability import list_render_logs

        payload = await list_render_logs(limit=80, direction="backward")
        if not isinstance(payload, list):
            return None

        sha7 = head_sha[:7]
        lines: List[str] = []
        for item in reversed(payload):
            if not isinstance(item, dict):
                continue
            msg = str(item.get("message") or item.get("text") or item.get("log") or "").strip()
            if not msg:
                continue
            low = msg.lower()
            if sha7 and sha7 in msg:
                lines.append(msg)
            elif any(
                k in low for k in ("deploy", "build", "starting", "pulling", "running", "live")
            ):
                lines.append(msg)
            if len(lines) >= max_lines:
                break

        return lines or None
    except Exception:
        return None


async def _update_session_log_after_push(
    *,
    deps: Dict[str, Any],
    repo_dir: str,
    full_name: str,
    branch: str,
    head_sha: str,
    head_summary: str,
    changed_lines: List[str],
    commit_message: str,
    session_summary: Optional[str],
    verification: Optional[str],
    next_steps: Optional[str],
) -> Dict[str, Any]:
    """Append a user-facing entry to the daily session log, then commit+push it."""

    if commit_message.strip().lower().startswith("chore(session_logs):"):
        return {"skipped": True, "reason": "session log commit"}

    changed = _format_status_summary(changed_lines)
    summary_text = (session_summary or "").strip() or commit_message.strip()

    ci_run = await _try_get_ci_run_summary(full_name=full_name, branch=branch, head_sha=head_sha)
    render_excerpt = await _try_get_render_log_excerpt(head_sha)
    render_health = None
    try:
        from github_mcp.main_tools.render_observability import get_render_health_summary as _health

        render_health = await _health()
    except Exception:
        render_health = None

    ts_local = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo

        ts_local = ts_local.astimezone(ZoneInfo("America/Toronto"))
    except Exception:
        pass

    md: List[str] = [
        f"## {ts_local.strftime('%Y-%m-%d %H:%M:%S %Z')} — Commit pushed",
        f"**Repo:** `{full_name}`  ",
        f"**Branch:** `{branch}`  ",
        f"**Commit:** `{head_sha[:7]}` — {head_summary or commit_message.strip()}",
        "",
        "### Summary",
        summary_text,
        "",
        "### Changed files",
        format_bullets(changed) if changed else "- (No file list captured)",
        "",
        "### Verification",
    ]

    md.append(f"- {(verification or 'Not recorded').strip()}")

    if ci_run and ci_run.get("html_url"):
        status = ci_run.get("status") or "unknown"
        conclusion = ci_run.get("conclusion")
        url = ci_run.get("html_url")
        if conclusion:
            md.append(f"- CI: {status} / {conclusion} — {url}")
        else:
            md.append(f"- CI: {status} — {url}")
    else:
        md.append("- CI: pending / not available")

    if render_health:
        health_lines = []
        window = render_health.get("window_minutes")
        cpu = render_health.get("cpu_percent")
        mem = render_health.get("memory_percent")
        lat = render_health.get("http_latency_recent_max_ms")
        req = render_health.get("http_requests_recent_max")
        inst = render_health.get("instance_count")
        if window is not None:
            health_lines.append(f"Window: last {int(window)} minutes")
        if cpu is not None:
            health_lines.append(f"CPU: ~{float(cpu):.0f}% of limit")
        if mem is not None:
            health_lines.append(f"Memory: ~{float(mem):.0f}% of limit")
        if lat is not None:
            health_lines.append(f"HTTP latency peak: ~{float(lat):.0f}ms")
        if req is not None:
            health_lines.append(f"HTTP requests peak: ~{float(req):.0f}")
        if inst is not None:
            health_lines.append(f"Instances: ~{float(inst):.0f}")
        warns = render_health.get("warnings")
        if isinstance(warns, list):
            for w in warns[:5]:
                if isinstance(w, str) and w.strip():
                    health_lines.append(f"Warning: {w.strip()}")
        if health_lines:
            md.append("- Deploy: Render health snapshot:")
            md.append(format_bullets(health_lines, max_items=12) or "")
    else:
        md.append("- Deploy: Render health snapshot: not available")

    if render_excerpt:
        md.append("- Deploy: recent Render log excerpt:")
        md.append(format_bullets(render_excerpt, max_items=6) or "")
    else:
        md.append("- Deploy: pending / not available")

    md.extend(["", "### Next steps"])
    md.append(
        (
            next_steps
            or "After CI is green, wait for the Render redeploy to complete, then verify behavior in the running service."
        ).strip()
    )

    entry_md = "\n".join(md).rstrip() + "\n"

    ctx = append_session_log_entry(repo_dir, entry_md)

    add_log = await deps["run_shell"](
        f"git add -- {ctx.rel_path}", cwd=repo_dir, timeout_seconds=60
    )
    if add_log["exit_code"] != 0:
        return {"error": "git add session log failed", "details": _slim_shell_result(add_log)}

    commit_msg = f"chore(session_logs): update for {head_sha[:7]}"
    commit_cmd = f"git commit -m {shlex.quote(commit_msg)}"
    commit_res = await deps["run_shell"](commit_cmd, cwd=repo_dir, timeout_seconds=120)
    if commit_res["exit_code"] != 0:
        combined = (commit_res.get("stderr") or commit_res.get("stdout") or "").lower()
        if "nothing to commit" in combined:
            return {
                "session_log_path": ctx.rel_path,
                "skipped": True,
                "reason": "no session log changes",
            }
        return {"error": "git commit session log failed", "details": _slim_shell_result(commit_res)}

    push_cmd = f"git push origin HEAD:{branch}"
    push_res = await deps["run_shell"](push_cmd, cwd=repo_dir, timeout_seconds=180)
    if push_res["exit_code"] != 0:
        return {"error": "git push session log failed", "details": _slim_shell_result(push_res)}

    rev = await deps["run_shell"]("git rev-parse HEAD", cwd=repo_dir, timeout_seconds=60)
    log_sha = rev.get("stdout", "").strip() if isinstance(rev, dict) else ""

    return {
        "session_log_path": ctx.rel_path,
        "session_log_commit_sha": log_sha,
        "session_log_commit": _slim_shell_result(commit_res),
        "session_log_push": _slim_shell_result(push_res),
    }


@mcp_tool(write_action=False)
async def commit_workspace(
    full_name: Optional[str] = None,
    ref: str = "main",
    message: str = "Commit workspace changes",
    add_all: bool = True,
    push: bool = True,
    update_session_log: Optional[bool] = None,
    session_summary: Optional[str] = None,
    verification: Optional[str] = None,
    next_steps: Optional[str] = None,
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
        if push:
            _tw()._ensure_write_allowed(
                f"commit_workspace for {full_name}@{effective_ref}",
                target_ref=effective_ref,
            )
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
        diff_text = (
            diff_before_commit.get("stdout", "") if isinstance(diff_before_commit, dict) else ""
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

        # Keep tool responses small to avoid connector transport issues.
        rev = await deps["run_shell"]("git rev-parse HEAD", cwd=repo_dir, timeout_seconds=60)
        head_sha = rev.get("stdout", "").strip() if isinstance(rev, dict) else ""
        oneline = await deps["run_shell"]("git log -1 --oneline", cwd=repo_dir, timeout_seconds=60)
        head_summary = oneline.get("stdout", "").strip() if isinstance(oneline, dict) else ""

        session_log = None
        if update_session_log is None:
            update_session_log = bool(push)
        if update_session_log and push:
            try:
                session_log = await _update_session_log_after_push(
                    deps=deps,
                    repo_dir=repo_dir,
                    full_name=full_name,
                    branch=effective_ref,
                    head_sha=head_sha,
                    head_summary=head_summary,
                    changed_lines=status_lines,
                    commit_message=message,
                    session_summary=session_summary,
                    verification=verification,
                    next_steps=next_steps,
                )
            except Exception as _exc:
                session_log = {"error": str(_exc)}

        try:
            config.TOOLS_LOGGER.chat(
                "Committed workspace changes (%s files).",
                len(status_lines),
                extra={
                    "repo": full_name,
                    "ref": effective_ref,
                    "event": "workspace_commit_diff_summary",
                },
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
                    extra={
                        "repo": full_name,
                        "ref": effective_ref,
                        "event": "workspace_commit_diff",
                    },
                )
        except Exception:
            pass

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "changed_files": status_lines[:200],
            "changed_files_truncated": len(status_lines) > 200,
            "commit_sha": head_sha,
            "commit_summary": head_summary,
            "commit": _slim_shell_result(commit_result),
            "push": _slim_shell_result(push_result) if push_result is not None else None,
            "session_log": session_log,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="commit_workspace")


@mcp_tool(write_action=False)
async def commit_workspace_files(
    full_name: Optional[str],
    files: List[str],
    ref: str = "main",
    message: str = "Commit selected workspace changes",
    push: bool = True,
    update_session_log: Optional[bool] = None,
    session_summary: Optional[str] = None,
    verification: Optional[str] = None,
    next_steps: Optional[str] = None,
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
        if push:
            _tw()._ensure_write_allowed(
                f"commit_workspace_files for {full_name}@{effective_ref}",
                target_ref=effective_ref,
            )
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
        diff_text_files = (
            diff_before_commit_files.get("stdout", "")
            if isinstance(diff_before_commit_files, dict)
            else ""
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

        # Keep tool responses small to avoid connector transport issues.
        rev = await deps["run_shell"]("git rev-parse HEAD", cwd=repo_dir, timeout_seconds=60)
        head_sha = rev.get("stdout", "").strip() if isinstance(rev, dict) else ""
        oneline = await deps["run_shell"]("git log -1 --oneline", cwd=repo_dir, timeout_seconds=60)
        head_summary = oneline.get("stdout", "").strip() if isinstance(oneline, dict) else ""

        session_log = None
        if update_session_log is None:
            update_session_log = bool(push)
        if update_session_log and push:
            try:
                porcelain = [f" M {p}" for p in staged_files]
                session_log = await _update_session_log_after_push(
                    deps=deps,
                    repo_dir=repo_dir,
                    full_name=full_name,
                    branch=effective_ref,
                    head_sha=head_sha,
                    head_summary=head_summary,
                    changed_lines=porcelain,
                    commit_message=message,
                    session_summary=session_summary,
                    verification=verification,
                    next_steps=next_steps,
                )
            except Exception as _exc:
                session_log = {"error": str(_exc)}

        try:
            config.TOOLS_LOGGER.chat(
                "Committed selected workspace changes (%s files).",
                len(staged_files),
                extra={
                    "repo": full_name,
                    "ref": effective_ref,
                    "event": "workspace_commit_diff_summary",
                },
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
                    extra={
                        "repo": full_name,
                        "ref": effective_ref,
                        "event": "workspace_commit_diff",
                    },
                )
        except Exception:
            pass

        return {
            "repo_dir": repo_dir,
            "branch": effective_ref,
            "staged_files": staged_files[:200],
            "staged_files_truncated": len(staged_files) > 200,
            "commit_sha": head_sha,
            "commit_summary": head_summary,
            "commit": _slim_shell_result(commit_result),
            "push": _slim_shell_result(push_result) if push_result is not None else None,
            "session_log": session_log,
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
