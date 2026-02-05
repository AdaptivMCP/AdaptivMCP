# High-level workspace workflows.

from __future__ import annotations

import re
import time
from typing import Any

from github_mcp.server import _structured_tool_error, mcp_tool

from ._shared import (
    _build_quality_suite_payload,
    _filter_kwargs_for_callable,
    _safe_branch_slug,
    _tw,
)
from .fs import _normalize_workspace_operations

_HUNK_RE = re.compile(r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@")


def _parse_unified_diff_hunks(
    diff_text: str,
    *,
    max_files: int,
    max_hunks_per_file: int,
) -> dict[str, list[dict[str, Any]]]:
    """Extract hunk ranges from a unified diff.

    Returns a mapping of destination paths (the `b/<path>` side) to hunks.
    Each hunk is a dict with: old_start, old_len, new_start, new_len.
    """

    files: dict[str, list[dict[str, Any]]] = {}
    cur_path: str | None = None

    for raw in (diff_text or "").splitlines():
        if raw.startswith("diff --git "):
            parts = raw.split()
            if len(parts) >= 4:
                b_path = parts[3]
                if b_path.startswith("b/"):
                    b_path = b_path[2:]
                if b_path not in files and len(files) < max_files:
                    files[b_path] = []
                    cur_path = b_path
                else:
                    cur_path = b_path if b_path in files else None
            continue

        if cur_path is None:
            continue
        if len(files.get(cur_path, [])) >= max_hunks_per_file:
            continue

        m = _HUNK_RE.match(raw)
        if not m:
            continue
        old_start = int(m.group(1))
        old_len = int(m.group(2) or "1")
        new_start = int(m.group(3))
        new_len = int(m.group(4) or "1")
        files[cur_path].append(
            {
                "old_start": old_start,
                "old_len": old_len,
                "new_start": new_start,
                "new_len": new_len,
            }
        )

    return {p: hs for p, hs in files.items() if hs}


def _excerpt_window(
    *, start: int, length: int, context: int, max_lines: int
) -> tuple[int, int]:
    """Compute (start_line, max_lines) for an excerpt window around a hunk."""

    if start < 1:
        start = 1
    if length < 0:
        length = 0
    win_start = max(1, start - context)
    win_len = length + (2 * context)
    if win_len < 1:
        win_len = max(1, context * 2)
    if win_len > max_lines:
        win_len = max_lines
    return win_start, win_len


def _step(
    steps: list[dict[str, Any]],
    action: str,
    detail: str,
    *,
    status: str = "ok",
    **extra: Any,
) -> None:
    payload: dict[str, Any] = {
        "ts": time.time(),
        "action": action,
        "detail": detail,
        "status": status,
    }
    payload.update(extra)
    steps.append(payload)


def _error_return(
    *,
    steps: list[dict[str, Any]],
    action: str,
    detail: str,
    reason: str,
    **payload: Any,
) -> dict[str, Any]:
    """Append a terminal error step and return a stable error envelope.

    This workflow is UI-oriented: callers rely on the returned `steps` list to
    render what happened. Historically we returned early on failure without
    recording a step, which made errors look "skipped" in clients.
    """

    _step(steps, action, detail, status="error", reason=reason)
    return {"status": "error", "ok": False, "reason": reason, "steps": steps, **payload}


def _extract_error_message(payload: Any) -> str:
    """Best-effort extraction of an error message from tool payloads."""

    if not isinstance(payload, dict):
        return ""

    for key in ("error", "message", "detail"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    err_detail = payload.get("error_detail")
    if isinstance(err_detail, dict):
        for key in ("message", "detail"):
            val = err_detail.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    return ""


def _is_missing_remote_ref_error(payload: Any, *, ref: str | None = None) -> bool:
    """Heuristic: does a tool error look like a missing remote ref/branch?"""

    msg = _extract_error_message(payload).lower()
    if not msg:
        return False

    needles = (
        "unknown revision",
        "unknown revision or path",
        "ambiguous argument",
        "could not resolve",
        "remote ref",
        "remote branch",
        "rev-parse",
    )
    if not any(n in msg for n in needles):
        return False

    if ref:
        ref_l = ref.lower()
        if f"origin/{ref_l}" in msg:
            return True
        if ref_l in msg and "origin/" in msg:
            return True
        return False

    return True


@mcp_tool(write_action=True)
async def workspace_apply_ops_and_open_pr(
    full_name: str,
    *,
    base_ref: str = "main",
    feature_ref: str | None = None,
    operations: list[dict[str, Any]] | None = None,
    pr_title: str | None = None,
    pr_body: str | None = None,
    draft: bool = False,
    commit_message: str = "Apply workspace operations",
    sync_base_to_remote: bool = True,
    discard_local_changes: bool = True,
    run_quality: bool = True,
    quality_timeout_seconds: float = 0,
    test_command: str = "pytest -q",
    lint_command: str = "ruff check .",
    sync_args: dict[str, Any] | None = None,
    create_branch_args: dict[str, Any] | None = None,
    apply_ops_args: dict[str, Any] | None = None,
    quality_args: dict[str, Any] | None = None,
    pr_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply workspace operations on a new branch and open a PR.

    This is a convenience workflow that chains together the common sequence:

      1) Optionally reset the base workspace mirror to match origin.
      2) Create a fresh feature branch (or reuse `feature_ref`).
      3) Apply a list of `apply_workspace_operations` edits.
      4) Optionally run the quality suite.
      5) Commit + push changes.
      6) Open a PR back to `base_ref`.

    Returns a JSON payload with per-step logs for UI rendering.

    Notes:
      - `operations` uses the same schema as `apply_workspace_operations`.
      - If `run_quality` is true and the quality suite fails, no commit/PR is created.
    """

    steps: list[dict[str, Any]] = []

    try:
        if operations is None:
            operations = []
        if not isinstance(operations, list) or any(
            not isinstance(op, dict) for op in operations
        ):
            raise TypeError("operations must be a list of dicts")
        operations = _normalize_workspace_operations(operations)
        if not operations:
            raise ValueError("operations must contain at least one operation")

        tw = _tw()

        effective_base = tw._effective_ref_for_repo(full_name, base_ref)

        _step(
            steps,
            "Start workflow",
            f"Preparing to apply {len(operations)} operation(s) and open a PR into '{effective_base}'.",
            base_ref=effective_base,
        )

        sync_res: Any = None
        if sync_base_to_remote:
            _step(
                steps,
                "Sync base",
                f"Resetting workspace mirror for '{effective_base}' to match origin.",
            )
            extra_sync = dict(sync_args or {})
            extra_sync.pop("full_name", None)
            extra_sync.pop("ref", None)
            sync_call = {
                "full_name": full_name,
                "ref": effective_base,
                "discard_local_changes": discard_local_changes,
                **extra_sync,
            }
            sync_res = await tw.workspace_sync_to_remote(
                **_filter_kwargs_for_callable(tw.workspace_sync_to_remote, sync_call)
            )
            if isinstance(sync_res, dict) and sync_res.get("status") == "error":
                return _error_return(
                    steps=steps,
                    action="Sync base",
                    detail="Failed to sync base workspace mirror.",
                    reason="sync_base_failed",
                    sync=sync_res,
                )
            _step(steps, "Sync base", "Base workspace mirror is ready.", sync=sync_res)
        else:
            _step(
                steps,
                "Sync base",
                "Skipped base sync (sync_base_to_remote=false).",
                status="skip",
            )

        # Create a unique feature branch if none was provided.
        provided_feature = bool(feature_ref is not None and str(feature_ref).strip())
        if not provided_feature:
            feature_ref = f"workflow/{_safe_branch_slug(commit_message)}-{tw.uuid.uuid4().hex[:10]}"
        feature_ref = _safe_branch_slug(str(feature_ref))

        branch_res: Any = None
        if provided_feature:
            # Idempotency: if the caller supplied a feature branch, assume it may
            # already exist and avoid hard-failing when it does.
            _step(
                steps,
                "Create branch",
                f"Reusing existing feature branch '{feature_ref}'.",
                feature_ref=feature_ref,
            )

            extra_sync = dict(sync_args or {})
            extra_sync.pop("full_name", None)
            extra_sync.pop("ref", None)
            sync_feature_call = {
                "full_name": full_name,
                "ref": feature_ref,
                "discard_local_changes": discard_local_changes,
                **extra_sync,
            }
            feature_sync_res = await tw.workspace_sync_to_remote(
                **_filter_kwargs_for_callable(
                    tw.workspace_sync_to_remote, sync_feature_call
                )
            )

            if (
                isinstance(feature_sync_res, dict)
                and feature_sync_res.get("status") == "error"
            ):
                # If the branch doesn't exist remotely, fall back to creating it.
                if _is_missing_remote_ref_error(feature_sync_res, ref=feature_ref):
                    provided_feature = False
                else:
                    return _error_return(
                        steps=steps,
                        action="Create branch",
                        detail="Failed to sync feature branch mirror.",
                        reason="sync_feature_failed",
                        sync=sync_res,
                        branch=feature_sync_res,
                    )
            else:
                branch_res = {"ok": True, "reused": True, "sync": feature_sync_res}
                _step(
                    steps,
                    "Create branch",
                    "Feature branch mirror is ready.",
                    branch=branch_res,
                )

        if not provided_feature:
            _step(
                steps,
                "Create branch",
                f"Creating feature branch '{feature_ref}' from '{effective_base}'.",
                feature_ref=feature_ref,
            )
            extra_branch = dict(create_branch_args or {})
            extra_branch.pop("full_name", None)
            extra_branch.pop("base_ref", None)
            extra_branch.pop("new_branch", None)
            branch_call = {
                "full_name": full_name,
                "base_ref": effective_base,
                "new_branch": feature_ref,
                "push": True,
                **extra_branch,
            }
            branch_res = await tw.workspace_create_branch(
                **_filter_kwargs_for_callable(tw.workspace_create_branch, branch_call)
            )
            if isinstance(branch_res, dict) and branch_res.get("status") == "error":
                return _error_return(
                    steps=steps,
                    action="Create branch",
                    detail="Failed to create feature branch.",
                    reason="create_branch_failed",
                    sync=sync_res,
                    branch=branch_res,
                )
            _step(steps, "Create branch", "Feature branch ready.", branch=branch_res)

        _step(steps, "Apply operations", f"Applying {len(operations)} operation(s).")
        extra_ops = dict(apply_ops_args or {})
        extra_ops.pop("full_name", None)
        extra_ops.pop("ref", None)
        extra_ops.pop("operations", None)
        ops_call = {
            "full_name": full_name,
            "ref": feature_ref,
            "operations": operations,
            "fail_fast": True,
            "rollback_on_error": True,
            "preview_only": False,
            **extra_ops,
        }
        ops_res = await tw.apply_workspace_operations(
            **_filter_kwargs_for_callable(tw.apply_workspace_operations, ops_call)
        )
        if isinstance(ops_res, dict) and ops_res.get("status") == "error":
            return _error_return(
                steps=steps,
                action="Apply operations",
                detail="Failed to apply workspace operations.",
                reason="apply_operations_failed",
                sync=sync_res,
                branch=branch_res,
                operations=ops_res,
            )
        if isinstance(ops_res, dict) and ops_res.get("ok") is False:
            return _error_return(
                steps=steps,
                action="Apply operations",
                detail="Operations applied partially; at least one operation failed.",
                reason="apply_operations_partial",
                sync=sync_res,
                branch=branch_res,
                operations=ops_res,
            )
        _step(steps, "Apply operations", "Operations applied.", operations=ops_res)

        quality_res: Any = None
        if run_quality:
            _step(steps, "Quality suite", "Running lint/tests before commit.")
            quality_call = _build_quality_suite_payload(
                full_name=full_name,
                ref=feature_ref,
                test_command=test_command,
                lint_command=lint_command,
                timeout_seconds=quality_timeout_seconds,
                fail_fast=True,
                developer_defaults=True,
                extra=quality_args,
            )
            quality_res = await tw.run_quality_suite(
                **_filter_kwargs_for_callable(tw.run_quality_suite, quality_call)
            )
            if isinstance(quality_res, dict) and quality_res.get("status") in {
                "failed",
                "error",
                "passed_with_warnings",
            }:
                return _error_return(
                    steps=steps,
                    action="Quality suite",
                    detail="Quality suite failed; changes were not committed and no PR was opened.",
                    reason="quality_suite_failed",
                    sync=sync_res,
                    branch=branch_res,
                    operations=ops_res,
                    quality=quality_res,
                )
            _step(steps, "Quality suite", "Quality suite passed.", quality=quality_res)
        else:
            _step(
                steps,
                "Quality suite",
                "Skipped quality suite (run_quality=false).",
                status="skip",
            )

        title = pr_title or f"{feature_ref} -> {effective_base}"
        _step(steps, "Commit + PR", "Committing changes and opening PR.", title=title)
        extra_pr = dict(pr_args or {})
        extra_pr.pop("full_name", None)
        extra_pr.pop("ref", None)
        extra_pr.pop("base", None)
        pr_call = {
            "full_name": full_name,
            "ref": feature_ref,
            "base": effective_base,
            "title": title,
            "body": pr_body,
            "draft": bool(draft),
            "commit_message": commit_message,
            "run_quality": False,
            **extra_pr,
        }
        pr_res = await tw.commit_and_open_pr_from_workspace(
            **_filter_kwargs_for_callable(tw.commit_and_open_pr_from_workspace, pr_call)
        )
        if isinstance(pr_res, dict) and pr_res.get("status") == "error":
            return _error_return(
                steps=steps,
                action="Commit + PR",
                detail="Failed to commit and/or open PR.",
                reason="commit_or_pr_failed",
                sync=sync_res,
                branch=branch_res,
                operations=ops_res,
                quality=quality_res,
                pr=pr_res,
            )

        _step(
            steps,
            "Done",
            "Workflow completed.",
            pr_url=pr_res.get("pr_url") if isinstance(pr_res, dict) else None,
            pr_number=pr_res.get("pr_number") if isinstance(pr_res, dict) else None,
        )

        return {
            "status": "ok",
            "full_name": full_name,
            "base_ref": effective_base,
            "feature_ref": feature_ref,
            "sync": sync_res,
            "branch": branch_res,
            "operations": ops_res,
            "quality": quality_res,
            "pr": pr_res,
            "pr_url": pr_res.get("pr_url") if isinstance(pr_res, dict) else None,
            "pr_number": pr_res.get("pr_number") if isinstance(pr_res, dict) else None,
            "steps": steps,
        }
    except Exception as exc:
        # Always return steps so UIs can render what happened.
        _step(
            steps,
            "Error",
            f"Unhandled exception: {exc.__class__.__name__}: {exc}",
            status="error",
        )
        payload = _structured_tool_error(exc, context="workspace_apply_ops_and_open_pr")
        if isinstance(payload, dict) and "steps" not in payload:
            payload["steps"] = steps
        return payload


@mcp_tool(write_action=True)
async def workspace_manage_folders_and_open_pr(
    full_name: str,
    *,
    base_ref: str = "main",
    feature_ref: str | None = None,
    create_paths: list[str] | None = None,
    delete_paths: list[str] | None = None,
    allow_recursive: bool = False,
    allow_missing: bool = True,
    pr_title: str | None = None,
    pr_body: str | None = None,
    draft: bool = False,
    commit_message: str = "Manage workspace folders",
    sync_base_to_remote: bool = True,
    discard_local_changes: bool = True,
    run_quality: bool = True,
    quality_timeout_seconds: float = 0,
    test_command: str = "pytest -q",
    lint_command: str = "ruff check .",
    mkdir_args: dict[str, Any] | None = None,
    rmdir_args: dict[str, Any] | None = None,
    workflow_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create/remove folders on a branch and open a PR.

    This workflow converts folder operations into `apply_workspace_operations`
    steps, then delegates to `workspace_apply_ops_and_open_pr`.
    """

    try:
        operations: list[dict[str, Any]] = []
        if create_paths is None:
            create_paths = []
        if delete_paths is None:
            delete_paths = []

        if not isinstance(create_paths, list) or any(
            not isinstance(p, str) for p in create_paths
        ):
            raise TypeError("create_paths must be a list of strings")
        if not isinstance(delete_paths, list) or any(
            not isinstance(p, str) for p in delete_paths
        ):
            raise TypeError("delete_paths must be a list of strings")

        def _clean_paths(values: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for raw in values:
                if not isinstance(raw, str):
                    continue
                p = raw.strip()
                if not p:
                    continue
                if p in seen:
                    continue
                seen.add(p)
                out.append(p)
            return out

        create_paths = _clean_paths(create_paths)
        delete_paths = _clean_paths(delete_paths)

        conflict = set(create_paths).intersection(delete_paths)
        if conflict:
            raise ValueError(
                f"Paths cannot be both created and deleted in one call: {sorted(conflict)}"
            )

        for path in create_paths:
            op: dict[str, Any] = {"op": "mkdir", "path": path}
            extra = dict(mkdir_args or {})
            extra.pop("op", None)
            extra.pop("path", None)
            op.update(extra)
            operations.append(op)

        for path in delete_paths:
            op = {
                "op": "rmdir",
                "path": path,
                "allow_recursive": bool(allow_recursive),
                "allow_missing": bool(allow_missing),
            }
            extra = dict(rmdir_args or {})
            extra.pop("op", None)
            extra.pop("path", None)
            # Let explicit allow_recursive/allow_missing params remain the default
            # unless overridden via rmdir_args.
            op.update(extra)
            operations.append(op)

        if not operations:
            raise ValueError(
                "At least one create_paths or delete_paths entry is required"
            )

        tw = _tw()
        extra_flow = dict(workflow_args or {})
        extra_flow.pop("full_name", None)
        flow_call = {
            "full_name": full_name,
            "base_ref": base_ref,
            "feature_ref": feature_ref,
            "operations": operations,
            "pr_title": pr_title,
            "pr_body": pr_body,
            "draft": draft,
            "commit_message": commit_message,
            "sync_base_to_remote": sync_base_to_remote,
            "discard_local_changes": discard_local_changes,
            "run_quality": run_quality,
            "quality_timeout_seconds": quality_timeout_seconds,
            "test_command": test_command,
            "lint_command": lint_command,
            **extra_flow,
        }
        return await tw.workspace_apply_ops_and_open_pr(
            **_filter_kwargs_for_callable(tw.workspace_apply_ops_and_open_pr, flow_call)
        )
    except Exception as exc:
        return _structured_tool_error(
            exc, context="workspace_manage_folders_and_open_pr"
        )


@mcp_tool(write_action=False)
async def workspace_change_report(
    full_name: str,
    *,
    base_ref: str = "main",
    head_ref: str | None = None,
    ref: str = "main",
    max_files: int = 25,
    max_hunks_per_file: int = 3,
    diff_context_lines: int = 3,
    excerpt_context_lines: int = 8,
    excerpt_max_lines: int = 160,
    max_diff_chars: int | None = None,
    max_excerpt_chars: int = 80_000,
    include_diff: bool = True,
    git_diff_args: dict[str, Any] | None = None,
    excerpt_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single-call "what changed" report between two refs.

    Produces:
      - unified diff + numstat
      - parsed hunk ranges per file
      - contextual excerpts around each hunk from both base and head versions
    """

    steps: list[dict[str, Any]] = []
    try:
        tw = _tw()

        effective_base = tw._effective_ref_for_repo(full_name, base_ref)
        effective_head = tw._effective_ref_for_repo(full_name, head_ref or ref)

        if not isinstance(max_files, int) or max_files < 1:
            raise ValueError("max_files must be an int >= 1")
        if not isinstance(max_hunks_per_file, int) or max_hunks_per_file < 1:
            raise ValueError("max_hunks_per_file must be an int >= 1")
        if not isinstance(diff_context_lines, int) or diff_context_lines < 0:
            raise ValueError("diff_context_lines must be an int >= 0")
        if not isinstance(excerpt_context_lines, int) or excerpt_context_lines < 0:
            raise ValueError("excerpt_context_lines must be an int >= 0")
        if not isinstance(excerpt_max_lines, int) or excerpt_max_lines < 1:
            raise ValueError("excerpt_max_lines must be an int >= 1")
        if max_diff_chars is not None and (
            not isinstance(max_diff_chars, int) or max_diff_chars < 1
        ):
            raise ValueError("max_diff_chars must be an int >= 1 or None")
        if not isinstance(max_excerpt_chars, int) or max_excerpt_chars < 1:
            raise ValueError("max_excerpt_chars must be an int >= 1")

        _step(
            steps,
            "Start",
            f"Building change report: '{effective_base}' -> '{effective_head}'.",
            base_ref=effective_base,
            head_ref=effective_head,
        )

        _step(steps, "Diff", "Computing git diff + numstat.")
        extra_diff = dict(git_diff_args or {})
        extra_diff.pop("full_name", None)
        extra_diff.pop("ref", None)
        diff_call = {
            "full_name": full_name,
            "ref": effective_head,
            "left_ref": effective_base,
            "right_ref": effective_head,
            "staged": False,
            "paths": None,
            "context_lines": int(diff_context_lines),
            "max_chars": int(max_diff_chars) if max_diff_chars is not None else None,
            "color": False,
            **extra_diff,
        }
        diff_res = await tw.workspace_git_diff(
            **_filter_kwargs_for_callable(tw.workspace_git_diff, diff_call)
        )
        if isinstance(diff_res, dict) and diff_res.get("status") == "error":
            return _error_return(
                steps=steps,
                action="Diff",
                detail="Failed to compute git diff.",
                reason="diff_failed",
                diff=diff_res,
            )

        diff_text = (diff_res.get("diff") if isinstance(diff_res, dict) else "") or ""
        numstat = (
            diff_res.get("numstat") if isinstance(diff_res, dict) else None
        ) or []

        hunks_by_path = _parse_unified_diff_hunks(
            diff_text,
            max_files=int(max_files),
            max_hunks_per_file=int(max_hunks_per_file),
        )

        files: list[dict[str, Any]] = []
        for entry in numstat:
            path = entry.get("path")
            if not isinstance(path, str) or not path:
                continue

            if path not in hunks_by_path:
                files.append(
                    {"path": path, "numstat": entry, "hunks": [], "excerpts": []}
                )
                continue

            excerpts: list[dict[str, Any]] = []
            for h in hunks_by_path[path]:
                base_start, base_len = _excerpt_window(
                    start=int(h["old_start"]),
                    length=int(h["old_len"]),
                    context=int(excerpt_context_lines),
                    max_lines=int(excerpt_max_lines),
                )
                head_start, head_len = _excerpt_window(
                    start=int(h["new_start"]),
                    length=int(h["new_len"]),
                    context=int(excerpt_context_lines),
                    max_lines=int(excerpt_max_lines),
                )

                base_excerpt = await tw.read_git_file_excerpt(
                    **_filter_kwargs_for_callable(
                        tw.read_git_file_excerpt,
                        {
                            "full_name": full_name,
                            "ref": effective_head,
                            "path": path,
                            "git_ref": effective_base,
                            "start_line": base_start,
                            "max_lines": base_len,
                            "max_chars": int(max_excerpt_chars),
                            **{
                                k: v
                                for k, v in (excerpt_args or {}).items()
                                if k
                                not in {
                                    "full_name",
                                    "ref",
                                    "path",
                                    "git_ref",
                                    "start_line",
                                    "max_lines",
                                }
                            },
                        },
                    )
                )
                head_excerpt = await tw.read_git_file_excerpt(
                    **_filter_kwargs_for_callable(
                        tw.read_git_file_excerpt,
                        {
                            "full_name": full_name,
                            "ref": effective_head,
                            "path": path,
                            "git_ref": effective_head,
                            "start_line": head_start,
                            "max_lines": head_len,
                            "max_chars": int(max_excerpt_chars),
                            **{
                                k: v
                                for k, v in (excerpt_args or {}).items()
                                if k
                                not in {
                                    "full_name",
                                    "ref",
                                    "path",
                                    "git_ref",
                                    "start_line",
                                    "max_lines",
                                }
                            },
                        },
                    )
                )

                excerpts.append(
                    {
                        "hunk": h,
                        "base": {
                            "git_ref": effective_base,
                            "start_line": base_start,
                            "max_lines": base_len,
                            "result": base_excerpt,
                        },
                        "head": {
                            "git_ref": effective_head,
                            "start_line": head_start,
                            "max_lines": head_len,
                            "result": head_excerpt,
                        },
                    }
                )

            files.append(
                {
                    "path": path,
                    "numstat": entry,
                    "hunks": hunks_by_path.get(path, []),
                    "excerpts": excerpts,
                }
            )

        for path, hunks in hunks_by_path.items():
            if any(f.get("path") == path for f in files):
                continue
            files.append(
                {"path": path, "numstat": None, "hunks": hunks, "excerpts": []}
            )

        _step(steps, "Assemble", f"Prepared report for {len(files)} file(s).")

        out: dict[str, Any] = {
            "status": "ok",
            "full_name": full_name,
            "base_ref": effective_base,
            "head_ref": effective_head,
            "numstat": numstat,
            "files": files,
            "truncated": bool(diff_res.get("truncated"))
            if isinstance(diff_res, dict)
            else False,
            "steps": steps,
        }
        if include_diff:
            out["diff"] = diff_text
        return out
    except Exception as exc:
        _step(
            steps,
            "Error",
            f"Unhandled exception: {exc.__class__.__name__}: {exc}",
            status="error",
        )
        payload = _structured_tool_error(exc, context="workspace_change_report")
        if isinstance(payload, dict) and "steps" not in payload:
            payload["steps"] = steps
        return payload


@mcp_tool(write_action=False)
async def workspace_read_files_in_sections(
    full_name: str,
    ref: str = "main",
    paths: list[str] | None = None,
    *,
    start_line: int = 1,
    max_sections: int = 5,
    max_lines_per_section: int = 200,
    max_chars_per_section: int = 80_000,
    overlap_lines: int = 20,
    include_missing: bool = True,
) -> dict[str, Any]:
    """Read multiple workspace files as chunked sections with real line numbers.

    Convenience wrapper around `read_workspace_file_sections`.
    """

    try:
        if paths is None:
            paths = []
        if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
            raise TypeError("paths must be a list of strings")
        if not paths:
            raise ValueError("paths must contain at least one item")

        tw = _tw()
        effective_ref = tw._effective_ref_for_repo(full_name, ref)

        files: list[dict[str, Any]] = []
        missing: list[str] = []
        errors: list[dict[str, Any]] = []

        for p in paths:
            try:
                res = await tw.read_workspace_file_sections(
                    full_name=full_name,
                    ref=effective_ref,
                    path=p,
                    start_line=int(start_line),
                    max_sections=int(max_sections),
                    max_lines_per_section=int(max_lines_per_section),
                    max_chars_per_section=int(max_chars_per_section),
                    overlap_lines=int(overlap_lines),
                )
                if not res.get("exists"):
                    missing.append(p)
                    if include_missing:
                        files.append(res)
                else:
                    files.append(res)
            except Exception as exc:
                errors.append({"path": p, "error": str(exc)})

        ok = len(errors) == 0
        return {
            "full_name": full_name,
            "ref": effective_ref,
            "status": "ok" if ok else "partial",
            "ok": ok,
            "start_line": int(start_line),
            "max_sections": int(max_sections),
            "max_lines_per_section": int(max_lines_per_section),
            "max_chars_per_section": int(max_chars_per_section),
            "overlap_lines": int(overlap_lines),
            "files": files,
            "missing_paths": missing,
            "errors": errors,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="workspace_read_files_in_sections")
