# Workspace PR helpers.

from __future__ import annotations

from typing import Any, Dict, Optional

from github_mcp.server import _structured_tool_error, mcp_tool


def _tw():
    from github_mcp import tools_workspace as tw

    return tw


@mcp_tool(write_action=True)
async def commit_and_open_pr_from_workspace(
    full_name: Optional[str] = None,
    ref: str = "main",
    base: str = "main",
    title: Optional[str] = None,
    body: Optional[str] = None,
    draft: bool = False,
    commit_message: str = "Commit workspace changes",
    run_quality: bool = False,
    quality_timeout_seconds: float = 600,
    test_command: str = "pytest",
    lint_command: str = "ruff check .",
    *,
    owner: Optional[str] = None,
    repo: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Commit workspace changes on `ref` and open a PR into `base`.

    This helper is intended for the common "edit in workspace -> commit/push -> open PR" flow.

    Notes:
    - This tool only pushes to the current `ref` (feature branch). It does not mutate the base branch.
    - When `run_quality` is enabled, lint/tests run before the commit is created.
    """

    try:
        tw = _tw()
        full_name = tw._resolve_full_name(full_name, owner=owner, repo=repo)
        ref = tw._resolve_ref(ref, branch=branch)
        effective_ref = tw._effective_ref_for_repo(full_name, ref)
        effective_base = tw._effective_ref_for_repo(full_name, base)

        quality: Optional[Dict[str, Any]] = None
        if run_quality:
            quality = await tw.run_quality_suite(
                full_name=full_name,
                ref=effective_ref,
                test_command=test_command,
                lint_command=lint_command,
                timeout_seconds=quality_timeout_seconds,
                fail_fast=True,
                developer_defaults=True,
                auto_setup_repo=True,
                owner=owner,
                repo=repo,
                branch=branch,
            )
            if isinstance(quality, dict) and quality.get("status") in {
                "failed",
                "error",
            }:
                return {
                    "status": "error",
                    "reason": "quality_suite_failed",
                    "branch": effective_ref,
                    "base": effective_base,
                    "quality": quality,
                    "message": "Quality suite failed; changes were not committed and no PR was opened.",
                }

        commit_result = await tw.commit_workspace(
            full_name=full_name,
            ref=effective_ref,
            message=commit_message,
            add_all=True,
            push=True,
            owner=owner,
            repo=repo,
            branch=branch,
        )

        if isinstance(commit_result, dict) and commit_result.get("error"):
            return {
                "status": "error",
                "reason": "commit_failed",
                "branch": effective_ref,
                "base": effective_base,
                "quality": quality,
                "commit": commit_result,
            }

        pr_title = title or f"{effective_ref} -> {effective_base}"

        # Import here to avoid accidental import cycles at module load time.
        from github_mcp.main_tools.pull_requests import open_pr_for_existing_branch

        pr_result = await open_pr_for_existing_branch(
            full_name=full_name,
            branch=effective_ref,
            base=effective_base,
            title=pr_title,
            body=body,
            draft=draft,
        )

        if isinstance(pr_result, dict) and pr_result.get("status") == "error":
            return {
                "status": "error",
                "reason": "pr_open_failed",
                "branch": effective_ref,
                "base": effective_base,
                "quality": quality,
                "commit": commit_result,
                "pr": pr_result,
            }

        return {
            "status": "ok",
            "branch": effective_ref,
            "base": effective_base,
            "quality": quality,
            "commit": commit_result,
            "pr": pr_result,
            "pr_url": pr_result.get("pr_url") if isinstance(pr_result, dict) else None,
            "pr_number": pr_result.get("pr_number") if isinstance(pr_result, dict) else None,
        }
    except Exception as exc:
        return _structured_tool_error(exc, context="commit_and_open_pr_from_workspace")

