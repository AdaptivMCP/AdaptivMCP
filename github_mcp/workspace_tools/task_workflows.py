# High-level task lifecycle workflows.

from __future__ import annotations

import time
from typing import Any, Literal

from github_mcp.server import _structured_tool_error, mcp_tool

from ._shared import (
    _build_quality_suite_payload,
    _filter_kwargs_for_callable,
    _safe_branch_slug,
    _tw,
)


def _step(
    steps: list[dict[str, Any]],
    action: str,
    detail: str,
    *,
    status: str = "ok",
    **extra: Any,
) -> None:
    steps.append(
        {
            "ts": time.time(),
            "action": action,
            "detail": detail,
            "status": status,
            **extra,
        }
    )


def _summarize_tree(tree: Any) -> dict[str, Any] | None:
    if not isinstance(tree, dict):
        return None
    results = tree.get("results")
    file_count = 0
    dir_count = 0
    if isinstance(results, list):
        for entry in results:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("type")
            if entry_type == "file":
                file_count += 1
            elif entry_type == "dir":
                dir_count += 1
    return {
        "full_name": tree.get("full_name"),
        "ref": tree.get("ref"),
        "path": tree.get("path"),
        "cursor": tree.get("cursor"),
        "next_cursor": tree.get("next_cursor"),
        "max_entries": tree.get("max_entries"),
        "max_depth": tree.get("max_depth"),
        "include_hidden": tree.get("include_hidden"),
        "include_dirs": tree.get("include_dirs"),
        "result_count": len(results) if isinstance(results, list) else 0,
        "file_count": file_count,
        "dir_count": dir_count,
        "truncated": tree.get("truncated"),
    }


def _summarize_search_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    matches = result.get("matches")
    file_count = 0
    if isinstance(matches, list):
        file_count = len(
            {m.get("path") for m in matches if isinstance(m, dict) and m.get("path")}
        )
    return {
        "query": result.get("query"),
        "path": result.get("path"),
        "engine": result.get("engine"),
        "max_results": result.get("max_results"),
        "context_lines": result.get("context_lines"),
        "match_count": len(matches) if isinstance(matches, list) else 0,
        "file_count": file_count,
        "truncated": result.get("truncated"),
    }


def _summarize_operations_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    results = result.get("results")
    ok_count = 0
    error_count = 0
    if isinstance(results, list):
        for entry in results:
            if not isinstance(entry, dict):
                continue
            status = entry.get("status")
            if status == "ok":
                ok_count += 1
            elif status == "error":
                error_count += 1
    return {
        "ref": result.get("ref"),
        "status": result.get("status"),
        "ok": result.get("ok"),
        "preview_only": result.get("preview_only"),
        "operation_count": len(results) if isinstance(results, list) else 0,
        "ok_count": ok_count,
        "error_count": error_count,
    }


def _summarize_quality_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    steps = result.get("steps")
    failed_steps: list[str] = []
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            status = step.get("status")
            name = step.get("name")
            if status in {"failed", "error"} and isinstance(name, str):
                failed_steps.append(name)
    return {
        "status": result.get("status"),
        "step_count": len(steps) if isinstance(steps, list) else 0,
        "failed_steps": failed_steps,
    }


def _summarize_change_report(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    files = result.get("files")
    numstat = result.get("numstat")
    return {
        "status": result.get("status"),
        "full_name": result.get("full_name"),
        "base_ref": result.get("base_ref"),
        "head_ref": result.get("head_ref"),
        "file_count": len(files) if isinstance(files, list) else 0,
        "numstat_count": len(numstat) if isinstance(numstat, list) else 0,
        "truncated": result.get("truncated"),
    }


def _summarize_sync_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    before = result.get("before")
    after = result.get("after")
    return {
        "branch": result.get("branch"),
        "full_name": result.get("full_name"),
        "discard_local_changes": result.get("discard_local_changes"),
        "before": {
            "ahead": before.get("ahead"),
            "behind": before.get("behind"),
            "is_clean": before.get("is_clean"),
        }
        if isinstance(before, dict)
        else None,
        "after": {
            "ahead": after.get("ahead"),
            "behind": after.get("behind"),
            "is_clean": after.get("is_clean"),
        }
        if isinstance(after, dict)
        else None,
    }


def _summarize_branch_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    return {
        "base_ref": result.get("base_ref"),
        "new_branch": result.get("new_branch"),
        "moved_workspace": result.get("moved_workspace"),
    }


def _summarize_finalize_result(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    summary = {
        "status": result.get("status"),
        "reason": result.get("reason"),
    }
    if isinstance(result.get("pr_url"), str):
        summary["pr_url"] = result.get("pr_url")
    if result.get("pr_number") is not None:
        summary["pr_number"] = result.get("pr_number")
    if isinstance(result.get("commit_sha"), str):
        summary["commit_sha"] = result.get("commit_sha")
    if isinstance(result.get("commit_summary"), str):
        summary["commit_summary"] = result.get("commit_summary")
    return summary


def _error_return(
    *,
    steps: list[dict[str, Any]],
    action: str,
    detail: str,
    reason: str,
    include_steps: bool = True,
    **payload: Any,
) -> dict[str, Any]:
    _step(steps, action, detail, status="error", reason=reason)
    base = {"status": "error", "ok": False, "reason": reason, **payload}
    if include_steps:
        base["steps"] = steps
    return base


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


def _clean_queries(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            continue
        query = raw.strip()
        if not query:
            continue
        if query in seen:
            continue
        seen.add(query)
        cleaned.append(query)
    return cleaned


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
        if ref_l in msg and ("origin/" in msg or "upstream origin" in msg or "origin" in msg):
            return True
        return False

    return True


@mcp_tool(write_action=False)
async def workspace_task_plan(
    full_name: str,
    *,
    ref: str = "main",
    queries: list[str] | None = None,
    max_tree_files: int = 400,
    max_tree_bytes: int = 200_000,
    max_search_results: int = 50,
    include_details: bool = False,
    include_steps: bool = False,
) -> dict[str, Any]:
    """Gather planning context for a task.

    This is a lightweight, read-only helper that aggregates:
    - a bounded workspace tree scan
    - optional ripgrep searches for provided queries
    - a suggested task workflow template (tool names + intent)

    Payload shaping:
      - include_details=true returns full tree/search payloads.
      - include_steps=true includes the workflow step log.
    """

    steps: list[dict[str, Any]] = []
    try:
        if queries is None:
            queries = []
        if not isinstance(queries, list) or any(
            not isinstance(q, str) for q in queries
        ):
            raise TypeError("queries must be a list[str]")
        if not isinstance(max_tree_files, int) or max_tree_files < 1:
            raise ValueError("max_tree_files must be an int >= 1")
        if not isinstance(max_tree_bytes, int) or max_tree_bytes < 1:
            raise ValueError("max_tree_bytes must be an int >= 1")
        if not isinstance(max_search_results, int) or max_search_results < 1:
            raise ValueError("max_search_results must be an int >= 1")

        tw = _tw()
        effective_ref = tw._effective_ref_for_repo(full_name, ref)

        _step(
            steps,
            "Plan",
            f"Collecting planning context for '{full_name}' at '{effective_ref}'.",
        )

        _step(steps, "Tree scan", "Scanning workspace tree (bounded).")
        tree = await tw.scan_workspace_tree(
            full_name=full_name,
            ref=effective_ref,
            max_files=max_tree_files,
            max_bytes=max_tree_bytes,
        )
        if isinstance(tree, dict) and tree.get("status") == "error":
            return _error_return(
                steps=steps,
                action="Tree scan",
                detail="Failed to scan workspace tree.",
                reason="tree_scan_failed",
                include_steps=include_steps,
                tree=tree,
            )
        _step(steps, "Tree scan", "Tree scan complete.")

        searches: list[dict[str, Any]] = []
        for q in _clean_queries(queries):
            _step(steps, "Search", f"rg: {q}")
            res = await tw.rg_search_workspace(
                full_name=full_name,
                ref=effective_ref,
                query=q,
                path="",
                max_results=max_search_results,
                context_lines=2,
            )
            searches.append({"query": q, "result": res})
            if isinstance(res, dict) and res.get("status") == "error":
                return _error_return(
                    steps=steps,
                    action="Search",
                    detail=f"Search failed for query: {q}.",
                    reason="search_failed",
                    include_steps=include_steps,
                    searches=searches,
                )

        template = [
            {
                "phase": "plan",
                "tool": "workspace_task_plan",
                "notes": "Collect repo context and locate relevant code paths.",
            },
            {
                "phase": "edit",
                "tool": "apply_workspace_operations",
                "notes": "Perform targeted edits with rollback-on-error.",
            },
            {
                "phase": "test",
                "tool": "run_quality_suite",
                "notes": "Run lint + tests (or run_tests/run_lint_suite).",
            },
            {
                "phase": "finalize",
                "tool": "workspace_task_execute",
                "notes": "Commit changes and open PR or commit-only.",
            },
        ]

        return {
            "status": "ok",
            "ok": True,
            "full_name": full_name,
            "ref": effective_ref,
            "tree_summary": _summarize_tree(tree),
            "search_summaries": [
                {
                    "query": entry.get("query"),
                    "summary": _summarize_search_result(entry.get("result")),
                }
                for entry in searches
                if isinstance(entry, dict)
            ],
            "workflow_template": template,
            **({"tree": tree, "searches": searches} if include_details else {}),
            **({"steps": steps} if include_steps else {}),
        }
    except Exception as exc:
        _step(
            steps,
            "Error",
            f"Unhandled exception: {exc.__class__.__name__}: {exc}",
            status="error",
        )
        payload = _structured_tool_error(exc, context="workspace_task_plan")
        if include_steps and isinstance(payload, dict) and "steps" not in payload:
            payload["steps"] = steps
        return payload


@mcp_tool(write_action=True)
async def workspace_task_apply_edits(
    full_name: str,
    *,
    ref: str = "main",
    operations: list[dict[str, Any]] | None = None,
    preview_only: bool = False,
    fail_fast: bool = True,
    rollback_on_error: bool = True,
    apply_ops_args: dict[str, Any] | None = None,
    include_details: bool = False,
    include_steps: bool = False,
) -> dict[str, Any]:
    """Apply a list of workspace edit operations with task-friendly defaults.

    Payload shaping:
      - include_details=true returns full operation results.
      - include_steps=true includes the workflow step log.
    """

    steps: list[dict[str, Any]] = []
    try:
        if operations is None:
            operations = []
        if not isinstance(operations, list) or any(
            not isinstance(op, dict) for op in operations
        ):
            raise TypeError("operations must be a list of dicts")
        if not operations:
            raise ValueError("operations must contain at least one operation")

        tw = _tw()
        effective_ref = tw._effective_ref_for_repo(full_name, ref)

        _step(
            steps,
            "Apply edits",
            f"Applying {len(operations)} operation(s) to '{full_name}' at '{effective_ref}'.",
            ref=effective_ref,
        )

        extra = dict(apply_ops_args or {})
        extra.pop("full_name", None)
        extra.pop("ref", None)
        extra.pop("operations", None)

        call = {
            "full_name": full_name,
            "ref": effective_ref,
            "operations": operations,
            "fail_fast": bool(fail_fast),
            "rollback_on_error": bool(rollback_on_error),
            "preview_only": bool(preview_only),
            **extra,
        }
        res = await tw.apply_workspace_operations(
            **_filter_kwargs_for_callable(tw.apply_workspace_operations, call)
        )
        if isinstance(res, dict) and res.get("status") == "error":
            return _error_return(
                steps=steps,
                action="Apply edits",
                detail="Failed to apply workspace operations.",
                reason="apply_edits_failed",
                include_steps=include_steps,
                operations=res,
            )
        if isinstance(res, dict) and res.get("ok") is False:
            return _error_return(
                steps=steps,
                action="Apply edits",
                detail="Operations applied partially; at least one operation failed.",
                reason="apply_edits_partial",
                include_steps=include_steps,
                operations=res,
            )

        _step(steps, "Apply edits", "Edits applied.")
        return {
            "status": "ok",
            "ok": True,
            "full_name": full_name,
            "ref": effective_ref,
            "operations_summary": _summarize_operations_result(res),
            **({"operations": res} if include_details else {}),
            **({"steps": steps} if include_steps else {}),
        }
    except Exception as exc:
        _step(
            steps,
            "Error",
            f"Unhandled exception: {exc.__class__.__name__}: {exc}",
            status="error",
        )
        payload = _structured_tool_error(exc, context="workspace_task_apply_edits")
        if include_steps and isinstance(payload, dict) and "steps" not in payload:
            payload["steps"] = steps
        return payload


FinalizeMode = Literal["pr", "commit_only"]


@mcp_tool(write_action=True)
async def workspace_task_execute(
    full_name: str,
    *,
    base_ref: str = "main",
    feature_ref: str | None = None,
    operations: list[dict[str, Any]] | None = None,
    commit_message: str = "Task updates",
    run_quality: bool = True,
    quality_timeout_seconds: float = 0,
    test_command: str = "pytest -q",
    lint_command: str = "ruff check .",
    finalize_mode: FinalizeMode = "pr",
    pr_title: str | None = None,
    pr_body: str | None = None,
    draft: bool = False,
    sync_base_to_remote: bool = True,
    discard_local_changes: bool = True,
    plan_queries: list[str] | None = None,
    sync_args: dict[str, Any] | None = None,
    create_branch_args: dict[str, Any] | None = None,
    apply_ops_args: dict[str, Any] | None = None,
    quality_args: dict[str, Any] | None = None,
    pr_args: dict[str, Any] | None = None,
    commit_args: dict[str, Any] | None = None,
    include_details: bool = False,
    include_steps: bool = False,
) -> dict[str, Any]:
    """End-to-end task workflow: plan -> edit/implement -> test -> finalize.

    - Planning: optional rg searches for `plan_queries` on the base ref.
    - Editing/implementing: applies `operations` onto a new feature branch.
    - Testing: optional lint+tests suite.
    - Finalizing: either opens a PR (`finalize_mode=pr`) or commits+pushes only.

    Payload shaping:
      - include_details=true returns full sub-tool payloads.
      - include_steps=true includes the workflow step log.
    """

    steps: list[dict[str, Any]] = []
    try:
        if operations is None:
            operations = []
        if not isinstance(operations, list) or any(
            not isinstance(op, dict) for op in operations
        ):
            raise TypeError("operations must be a list of dicts")
        if not operations:
            raise ValueError("operations must contain at least one operation")

        if plan_queries is None:
            plan_queries = []
        if not isinstance(plan_queries, list) or any(
            not isinstance(q, str) for q in plan_queries
        ):
            raise TypeError("plan_queries must be a list[str]")

        if not isinstance(commit_message, str) or not commit_message.strip():
            raise ValueError("commit_message must be a non-empty string")

        if finalize_mode not in {"pr", "commit_only"}:
            raise ValueError("finalize_mode must be one of: pr, commit_only")

        tw = _tw()
        effective_base = tw._effective_ref_for_repo(full_name, base_ref)

        _step(
            steps,
            "Start workflow",
            f"Preparing task workflow for '{full_name}' into '{effective_base}'.",
            base_ref=effective_base,
            finalize_mode=finalize_mode,
        )

        # Plan: lightweight search on base.
        searches: list[dict[str, Any]] = []
        for q in _clean_queries(plan_queries):
            _step(steps, "Plan search", f"rg: {q}")
            res = await tw.rg_search_workspace(
                full_name=full_name,
                ref=effective_base,
                query=q,
                path="",
                max_results=25,
                context_lines=2,
            )
            searches.append({"query": q, "result": res})
            if isinstance(res, dict) and res.get("status") == "error":
                return _error_return(
                    steps=steps,
                    action="Plan search",
                    detail=f"Search failed for query: {q}.",
                    reason="plan_search_failed",
                    include_steps=include_steps,
                    searches=searches,
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
                    include_steps=include_steps,
                    sync=sync_res,
                    searches=searches,
                )
            _step(steps, "Sync base", "Base workspace mirror is ready.")
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
            feature_ref = (
                f"task/{_safe_branch_slug(commit_message)}-{tw.uuid.uuid4().hex[:10]}"
            )
        feature_ref = _safe_branch_slug(str(feature_ref))

        branch_res: Any = None
        if provided_feature:
            # Idempotency: reuse a caller-provided branch instead of hard-failing.
            _step(
                steps,
                "Create branch",
                f"Reusing existing feature branch '{feature_ref}'.",
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
                if _is_missing_remote_ref_error(feature_sync_res, ref=feature_ref):
                    provided_feature = False
                else:
                    return _error_return(
                        steps=steps,
                        action="Create branch",
                        detail="Failed to sync feature branch mirror.",
                        reason="sync_feature_failed",
                        include_steps=include_steps,
                        sync=sync_res,
                        branch=feature_sync_res,
                        searches=searches,
                    )
            else:
                branch_res = {"ok": True, "reused": True, "sync": feature_sync_res}
                _step(steps, "Create branch", "Feature branch mirror is ready.")

        if not provided_feature:
            _step(
                steps,
                "Create branch",
                f"Creating feature branch '{feature_ref}' from '{effective_base}'.",
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
                    include_steps=include_steps,
                    sync=sync_res,
                    branch=branch_res,
                    searches=searches,
                )
            _step(steps, "Create branch", "Feature branch ready.")

        # Apply edits.
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
                include_steps=include_steps,
                sync=sync_res,
                branch=branch_res,
                operations=ops_res,
                searches=searches,
            )
        if isinstance(ops_res, dict) and ops_res.get("ok") is False:
            return _error_return(
                steps=steps,
                action="Apply operations",
                detail="Operations applied partially; at least one operation failed.",
                reason="apply_operations_partial",
                include_steps=include_steps,
                sync=sync_res,
                branch=branch_res,
                operations=ops_res,
                searches=searches,
            )
        _step(steps, "Apply operations", "Operations applied.")

        quality_res: Any = None
        if run_quality:
            _step(steps, "Quality suite", "Running lint/tests before finalize.")
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
                    detail="Quality suite failed; changes were not finalized.",
                    reason="quality_suite_failed",
                    include_steps=include_steps,
                    sync=sync_res,
                    branch=branch_res,
                    operations=ops_res,
                    quality=quality_res,
                    searches=searches,
                )
            _step(steps, "Quality suite", "Quality suite passed.")
        else:
            _step(
                steps,
                "Quality suite",
                "Skipped quality suite (run_quality=false).",
                status="skip",
            )

        # Change report + PR summary are useful in both finalize modes.
        _step(steps, "Report", "Building change report and summary.")
        change_report = await tw.workspace_change_report(
            full_name=full_name,
            base_ref=effective_base,
            head_ref=feature_ref,
            include_diff=False,
        )
        if isinstance(change_report, dict) and change_report.get("status") == "error":
            return _error_return(
                steps=steps,
                action="Report",
                detail="Failed to build change report.",
                reason="change_report_failed",
                include_steps=include_steps,
                sync=sync_res,
                branch=branch_res,
                operations=ops_res,
                quality=quality_res,
                report=change_report,
                searches=searches,
            )
        changed_files: list[str] = []
        if isinstance(change_report, dict):
            for f in change_report.get("files", []) or []:
                if isinstance(f, dict):
                    p = f.get("path")
                    if isinstance(p, str) and p:
                        changed_files.append(p)

        if finalize_mode == "pr":
            summary_title = pr_title or f"{feature_ref} -> {effective_base}"
            summary_body = pr_body or ""
        else:
            summary_title = commit_message
            summary_body = ""

        pr_summary = await tw.build_pr_summary(
            full_name=full_name,
            ref=feature_ref,
            title=summary_title,
            body=summary_body,
            changed_files=changed_files,
        )

        finalize_res: Any = None
        if finalize_mode == "pr":
            title = pr_title or f"{feature_ref} -> {effective_base}"
            _step(steps, "Finalize", "Committing changes and opening PR.", title=title)
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
            finalize_res = await tw.commit_and_open_pr_from_workspace(
                **_filter_kwargs_for_callable(
                    tw.commit_and_open_pr_from_workspace, pr_call
                )
            )
            if isinstance(finalize_res, dict) and finalize_res.get("status") == "error":
                return _error_return(
                    steps=steps,
                    action="Finalize",
                    detail="Failed to commit and/or open PR.",
                    reason="commit_or_pr_failed",
                    include_steps=include_steps,
                    sync=sync_res,
                    branch=branch_res,
                    operations=ops_res,
                    quality=quality_res,
                    report=change_report,
                    pr_summary=pr_summary,
                    pr=finalize_res,
                    searches=searches,
                )
        else:
            _step(steps, "Finalize", "Committing changes (commit-only).")
            extra_commit = dict(commit_args or {})
            extra_commit.pop("full_name", None)
            extra_commit.pop("ref", None)
            extra_commit.pop("message", None)
            commit_call = {
                "full_name": full_name,
                "ref": feature_ref,
                "message": commit_message,
                "add_all": True,
                "push": True,
                **extra_commit,
            }
            finalize_res = await tw.commit_workspace(
                **_filter_kwargs_for_callable(tw.commit_workspace, commit_call)
            )
            if isinstance(finalize_res, dict) and finalize_res.get("status") == "error":
                return _error_return(
                    steps=steps,
                    action="Finalize",
                    detail="Failed to commit and/or push changes.",
                    reason="commit_failed",
                    include_steps=include_steps,
                    sync=sync_res,
                    branch=branch_res,
                    operations=ops_res,
                    quality=quality_res,
                    report=change_report,
                    pr_summary=pr_summary,
                    commit=finalize_res,
                    searches=searches,
                )

        _step(steps, "Done", "Task workflow completed.")
        return {
            "status": "ok",
            "ok": True,
            "full_name": full_name,
            "base_ref": effective_base,
            "feature_ref": feature_ref,
            "finalize_mode": finalize_mode,
            "search_summaries": [
                {
                    "query": entry.get("query"),
                    "summary": _summarize_search_result(entry.get("result")),
                }
                for entry in searches
                if isinstance(entry, dict)
            ],
            "sync_summary": _summarize_sync_result(sync_res),
            "branch_summary": _summarize_branch_result(branch_res),
            "operations_summary": _summarize_operations_result(ops_res),
            "quality_summary": _summarize_quality_result(quality_res),
            "report_summary": _summarize_change_report(change_report),
            "finalize_summary": _summarize_finalize_result(finalize_res),
            **(
                {
                    "searches": searches,
                    "sync": sync_res,
                    "branch": branch_res,
                    "operations": ops_res,
                    "quality": quality_res,
                    "report": change_report,
                    "pr_summary": pr_summary,
                    "finalize": finalize_res,
                }
                if include_details
                else {}
            ),
            **({"steps": steps} if include_steps else {}),
        }
    except Exception as exc:
        _step(
            steps,
            "Error",
            f"Unhandled exception: {exc.__class__.__name__}: {exc}",
            status="error",
        )
        payload = _structured_tool_error(exc, context="workspace_task_execute")
        if include_steps and isinstance(payload, dict) and "steps" not in payload:
            payload["steps"] = steps
        return payload
