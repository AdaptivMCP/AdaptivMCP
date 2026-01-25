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


def _error_return(
    *,
    steps: list[dict[str, Any]],
    action: str,
    detail: str,
    reason: str,
    **payload: Any,
) -> dict[str, Any]:
    _step(steps, action, detail, status="error", reason=reason)
    return {"status": "error", "ok": False, "reason": reason, "steps": steps, **payload}


@mcp_tool(write_action=False)
async def workspace_task_plan(
    full_name: str,
    *,
    ref: str = "main",
    queries: list[str] | None = None,
    max_tree_files: int = 400,
    max_tree_bytes: int = 200_000,
    max_search_results: int = 50,
) -> dict[str, Any]:
    """Gather planning context for a task.

    This is a lightweight, read-only helper that aggregates:
    - a bounded workspace tree scan
    - optional ripgrep searches for provided queries
    - a suggested task workflow template (tool names + intent)
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
                tree=tree,
            )
        _step(steps, "Tree scan", "Tree scan complete.")

        searches: list[dict[str, Any]] = []
        for q in [qq.strip() for qq in queries if isinstance(qq, str) and qq.strip()]:
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
            "tree": tree,
            "searches": searches,
            "workflow_template": template,
            "steps": steps,
        }
    except Exception as exc:
        _step(
            steps,
            "Error",
            f"Unhandled exception: {exc.__class__.__name__}: {exc}",
            status="error",
        )
        payload = _structured_tool_error(exc, context="workspace_task_plan")
        if isinstance(payload, dict) and "steps" not in payload:
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
) -> dict[str, Any]:
    """Apply a list of workspace edit operations with task-friendly defaults."""

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
                operations=res,
            )
        if isinstance(res, dict) and res.get("ok") is False:
            return _error_return(
                steps=steps,
                action="Apply edits",
                detail="Operations applied partially; at least one operation failed.",
                reason="apply_edits_partial",
                operations=res,
            )

        _step(steps, "Apply edits", "Edits applied.")
        return {
            "status": "ok",
            "ok": True,
            "full_name": full_name,
            "ref": effective_ref,
            "operations": res,
            "steps": steps,
        }
    except Exception as exc:
        _step(
            steps,
            "Error",
            f"Unhandled exception: {exc.__class__.__name__}: {exc}",
            status="error",
        )
        payload = _structured_tool_error(exc, context="workspace_task_apply_edits")
        if isinstance(payload, dict) and "steps" not in payload:
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
) -> dict[str, Any]:
    """End-to-end task workflow: plan -> edit/implement -> test -> finalize.

    - Planning: optional rg searches for `plan_queries` on the base ref.
    - Editing/implementing: applies `operations` onto a new feature branch.
    - Testing: optional lint+tests suite.
    - Finalizing: either opens a PR (`finalize_mode=pr`) or commits+pushes only.
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
        for q in [
            qq.strip() for qq in plan_queries if isinstance(qq, str) and qq.strip()
        ]:
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
        if feature_ref is None or not str(feature_ref).strip():
            feature_ref = (
                f"task/{_safe_branch_slug(commit_message)}-{tw.uuid.uuid4().hex[:10]}"
            )
        feature_ref = _safe_branch_slug(str(feature_ref))

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
            }:
                return _error_return(
                    steps=steps,
                    action="Quality suite",
                    detail="Quality suite failed; changes were not finalized.",
                    reason="quality_suite_failed",
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
        pr_summary = await tw.build_pr_summary(full_name=full_name, ref=feature_ref)

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
            "searches": searches,
            "sync": sync_res,
            "branch": branch_res,
            "operations": ops_res,
            "quality": quality_res,
            "report": change_report,
            "pr_summary": pr_summary,
            "finalize_mode": finalize_mode,
            "finalize": finalize_res,
            "steps": steps,
        }
    except Exception as exc:
        _step(
            steps,
            "Error",
            f"Unhandled exception: {exc.__class__.__name__}: {exc}",
            status="error",
        )
        payload = _structured_tool_error(exc, context="workspace_task_execute")
        if isinstance(payload, dict) and "steps" not in payload:
            payload["steps"] = steps
        return payload
