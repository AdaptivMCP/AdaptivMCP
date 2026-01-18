# High-level workspace workflows.

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from github_mcp.server import _structured_tool_error, mcp_tool

from ._shared import _safe_branch_slug, _tw


def _step(
    steps: List[Dict[str, Any]],
    action: str,
    detail: str,
    *,
    status: str = "ok",
    **extra: Any,
) -> None:
    payload: Dict[str, Any] = {
        "ts": time.time(),
        "action": action,
        "detail": detail,
        "status": status,
    }
    payload.update(extra)
    steps.append(payload)


@mcp_tool(write_action=True)
async def workspace_apply_ops_and_open_pr(
    full_name: str,
    *,
    base_ref: str = "main",
    feature_ref: Optional[str] = None,
    operations: Optional[List[Dict[str, Any]]] = None,
    pr_title: Optional[str] = None,
    pr_body: Optional[str] = None,
    draft: bool = False,
    commit_message: str = "Apply workspace operations",
    sync_base_to_remote: bool = True,
    discard_local_changes: bool = True,
    run_quality: bool = True,
    quality_timeout_seconds: float = 600,
    test_command: str = "pytest",
    lint_command: str = "ruff check .",
) -> Dict[str, Any]:
    """Apply workspace operations on a new branch and open a PR.

    This is a convenience workflow that chains together the common sequence:

      1) Optionally reset the base workspace clone to match origin.
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

    try:
        if operations is None:
            operations = []
        if not isinstance(operations, list) or any(not isinstance(op, dict) for op in operations):
            raise TypeError("operations must be a list of dicts")
        if not operations:
            raise ValueError("operations must contain at least one operation")

        tw = _tw()
        steps: List[Dict[str, Any]] = []

        effective_base = tw._effective_ref_for_repo(full_name, base_ref)

        _step(
            steps,
            "Start workflow",
            f"Preparing to apply {len(operations)} operation(s) and open a PR into '{effective_base}'.",
            base_ref=effective_base,
        )

        sync_res = None
        if sync_base_to_remote:
            _step(
                steps,
                "Sync base",
                f"Resetting workspace clone for '{effective_base}' to match origin.",
            )
            sync_res = await tw.workspace_sync_to_remote(
                full_name=full_name,
                ref=effective_base,
                discard_local_changes=discard_local_changes,
            )
            if isinstance(sync_res, dict) and sync_res.get("status") == "error":
                return {
                    "status": "error",
                    "reason": "sync_base_failed",
                    "steps": steps,
                    "sync": sync_res,
                }
            _step(steps, "Sync base", "Base workspace clone is ready.", sync=sync_res)
        else:
            _step(
                steps, "Sync base", "Skipped base sync (sync_base_to_remote=false).", status="skip"
            )

        # Create a unique feature branch if none was provided.
        if feature_ref is None or not str(feature_ref).strip():
            feature_ref = f"workflow/{_safe_branch_slug(commit_message)}-{tw.uuid.uuid4().hex[:10]}"
        feature_ref = _safe_branch_slug(str(feature_ref))

        _step(
            steps,
            "Create branch",
            f"Creating feature branch '{feature_ref}' from '{effective_base}'.",
            feature_ref=feature_ref,
        )
        branch_res = await tw.workspace_create_branch(
            full_name=full_name,
            base_ref=effective_base,
            new_branch=feature_ref,
            push=True,
        )
        if isinstance(branch_res, dict) and branch_res.get("status") == "error":
            return {
                "status": "error",
                "reason": "create_branch_failed",
                "steps": steps,
                "sync": sync_res,
                "branch": branch_res,
            }
        _step(steps, "Create branch", "Feature branch ready.", branch=branch_res)

        _step(steps, "Apply operations", f"Applying {len(operations)} operation(s).")
        ops_res = await tw.apply_workspace_operations(
            full_name=full_name,
            ref=feature_ref,
            operations=operations,
            fail_fast=True,
            rollback_on_error=True,
            preview_only=False,
        )
        if isinstance(ops_res, dict) and ops_res.get("status") == "error":
            return {
                "status": "error",
                "reason": "apply_operations_failed",
                "steps": steps,
                "sync": sync_res,
                "branch": branch_res,
                "operations": ops_res,
            }
        if isinstance(ops_res, dict) and ops_res.get("ok") is False:
            return {
                "status": "error",
                "reason": "apply_operations_partial",
                "steps": steps,
                "sync": sync_res,
                "branch": branch_res,
                "operations": ops_res,
            }
        _step(steps, "Apply operations", "Operations applied.", operations=ops_res)

        quality_res = None
        if run_quality:
            _step(steps, "Quality suite", "Running lint/tests before commit.")
            quality_res = await tw.run_quality_suite(
                full_name=full_name,
                ref=feature_ref,
                test_command=test_command,
                lint_command=lint_command,
                timeout_seconds=quality_timeout_seconds,
                fail_fast=True,
                developer_defaults=False,
            )
            if isinstance(quality_res, dict) and quality_res.get("status") in {"failed", "error"}:
                return {
                    "status": "error",
                    "reason": "quality_suite_failed",
                    "steps": steps,
                    "sync": sync_res,
                    "branch": branch_res,
                    "operations": ops_res,
                    "quality": quality_res,
                    "message": "Quality suite failed; changes were not committed and no PR was opened.",
                }
            _step(steps, "Quality suite", "Quality suite passed.", quality=quality_res)
        else:
            _step(
                steps, "Quality suite", "Skipped quality suite (run_quality=false).", status="skip"
            )

        title = pr_title or f"{feature_ref} -> {effective_base}"
        _step(steps, "Commit + PR", "Committing changes and opening PR.", title=title)
        pr_res = await tw.commit_and_open_pr_from_workspace(
            full_name=full_name,
            ref=feature_ref,
            base=effective_base,
            title=title,
            body=pr_body,
            draft=bool(draft),
            commit_message=commit_message,
            run_quality=False,
        )
        if isinstance(pr_res, dict) and pr_res.get("status") == "error":
            return {
                "status": "error",
                "reason": "commit_or_pr_failed",
                "steps": steps,
                "sync": sync_res,
                "branch": branch_res,
                "operations": ops_res,
                "quality": quality_res,
                "pr": pr_res,
            }

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
        return _structured_tool_error(exc, context="workspace_apply_ops_and_open_pr")
