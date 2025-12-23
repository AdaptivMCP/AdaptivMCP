from __future__ import annotations

from enum import Enum
from typing import Dict


class SideEffectClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    LOCAL_MUTATION = "LOCAL_MUTATION"
    REMOTE_MUTATION = "REMOTE_MUTATION"


# Single source of truth for tool side-effect classification.
# This map is intentionally explicit to avoid drift between documentation,
# UI metadata, and server-side enforcement.
TOOL_SIDE_EFFECTS: Dict[str, SideEffectClass] = {
    "apply_text_update_and_commit": SideEffectClass.REMOTE_MUTATION,
    "authorize_write_actions": SideEffectClass.LOCAL_MUTATION,
    "build_pr_summary": SideEffectClass.READ_ONLY,
    "cache_files": SideEffectClass.LOCAL_MUTATION,
    "close_pull_request": SideEffectClass.REMOTE_MUTATION,
    "comment_on_issue": SideEffectClass.REMOTE_MUTATION,
    "comment_on_pull_request": SideEffectClass.REMOTE_MUTATION,
    # Workspace commit tools can push to origin; treat as remote mutations so they
    # always trigger connector UI approval.
    "commit_workspace": SideEffectClass.REMOTE_MUTATION,
    "commit_workspace_files": SideEffectClass.REMOTE_MUTATION,
    "create_branch": SideEffectClass.REMOTE_MUTATION,
    "create_file": SideEffectClass.REMOTE_MUTATION,
    "create_issue": SideEffectClass.REMOTE_MUTATION,
    "create_pull_request": SideEffectClass.REMOTE_MUTATION,
    "create_repository": SideEffectClass.REMOTE_MUTATION,
    "describe_tool": SideEffectClass.READ_ONLY,
    "download_user_content": SideEffectClass.READ_ONLY,
    "ensure_branch": SideEffectClass.REMOTE_MUTATION,
    "ensure_workspace_clone": SideEffectClass.LOCAL_MUTATION,
    "fetch_files": SideEffectClass.READ_ONLY,
    "fetch_issue": SideEffectClass.READ_ONLY,
    "fetch_issue_comments": SideEffectClass.READ_ONLY,
    "fetch_pr": SideEffectClass.READ_ONLY,
    "fetch_pr_comments": SideEffectClass.READ_ONLY,
    "fetch_url": SideEffectClass.READ_ONLY,
    "get_branch_summary": SideEffectClass.READ_ONLY,
    "get_cached_files": SideEffectClass.READ_ONLY,
    "get_commit_combined_status": SideEffectClass.READ_ONLY,
    "get_file_contents": SideEffectClass.READ_ONLY,
    "get_issue_comment_reactions": SideEffectClass.READ_ONLY,
    "get_issue_overview": SideEffectClass.READ_ONLY,
    "get_job_logs": SideEffectClass.READ_ONLY,
    "get_latest_branch_status": SideEffectClass.READ_ONLY,
    "get_pr_info": SideEffectClass.READ_ONLY,
    "get_pr_overview": SideEffectClass.READ_ONLY,
    "get_pr_reactions": SideEffectClass.READ_ONLY,
    "get_pr_review_comment_reactions": SideEffectClass.READ_ONLY,
    "get_rate_limit": SideEffectClass.READ_ONLY,
    "get_recent_server_errors": SideEffectClass.READ_ONLY,
    "get_recent_server_logs": SideEffectClass.READ_ONLY,
    "get_recent_tool_events": SideEffectClass.READ_ONLY,
    "get_render_metrics": SideEffectClass.READ_ONLY,
    "get_repo_dashboard": SideEffectClass.READ_ONLY,
    "get_repo_defaults": SideEffectClass.READ_ONLY,
    "get_repository": SideEffectClass.READ_ONLY,
    "get_server_config": SideEffectClass.READ_ONLY,
    "get_user_login": SideEffectClass.READ_ONLY,
    "get_workflow_run": SideEffectClass.READ_ONLY,
    "get_workflow_run_overview": SideEffectClass.READ_ONLY,
    "get_workspace_changes_summary": SideEffectClass.READ_ONLY,
    "get_workspace_file_contents": SideEffectClass.READ_ONLY,
    "graphql_query": SideEffectClass.READ_ONLY,
    "list_all_actions": SideEffectClass.READ_ONLY,
    "list_branches": SideEffectClass.READ_ONLY,
    "list_pr_changed_filenames": SideEffectClass.READ_ONLY,
    "list_pull_requests": SideEffectClass.READ_ONLY,
    "list_recent_failures": SideEffectClass.READ_ONLY,
    "list_recent_issues": SideEffectClass.READ_ONLY,
    "list_render_logs": SideEffectClass.READ_ONLY,
    "list_repositories": SideEffectClass.READ_ONLY,
    "list_repositories_by_installation": SideEffectClass.READ_ONLY,
    "list_repository_issues": SideEffectClass.READ_ONLY,
    "list_repository_tree": SideEffectClass.READ_ONLY,
    "list_tools": SideEffectClass.READ_ONLY,
    "list_workflow_run_jobs": SideEffectClass.READ_ONLY,
    "list_workflow_runs": SideEffectClass.READ_ONLY,
    "list_workspace_files": SideEffectClass.READ_ONLY,
    "list_write_tools": SideEffectClass.READ_ONLY,
    "merge_pull_request": SideEffectClass.REMOTE_MUTATION,
    "move_file": SideEffectClass.REMOTE_MUTATION,
    "open_issue_context": SideEffectClass.READ_ONLY,
    "open_pr_for_existing_branch": SideEffectClass.REMOTE_MUTATION,
    "pr_smoke_test": SideEffectClass.REMOTE_MUTATION,
    "recent_prs_for_branch": SideEffectClass.READ_ONLY,
    "render_shell": SideEffectClass.LOCAL_MUTATION,
    "resolve_handle": SideEffectClass.READ_ONLY,
    "run_command": SideEffectClass.LOCAL_MUTATION,
    "run_lint_suite": SideEffectClass.LOCAL_MUTATION,
    "run_quality_suite": SideEffectClass.LOCAL_MUTATION,
    "run_tests": SideEffectClass.LOCAL_MUTATION,
    "search": SideEffectClass.READ_ONLY,
    "search_workspace": SideEffectClass.READ_ONLY,
    "set_workspace_file_contents": SideEffectClass.LOCAL_MUTATION,
    "terminal_command": SideEffectClass.LOCAL_MUTATION,
    "trigger_and_wait_for_workflow": SideEffectClass.REMOTE_MUTATION,
    "trigger_workflow_dispatch": SideEffectClass.REMOTE_MUTATION,
    "update_files_and_open_pr": SideEffectClass.REMOTE_MUTATION,
    "update_issue": SideEffectClass.REMOTE_MUTATION,
    "validate_environment": SideEffectClass.READ_ONLY,
    "validate_json_string": SideEffectClass.READ_ONLY,
    "validate_tool_args": SideEffectClass.READ_ONLY,
    "wait_for_workflow_run": SideEffectClass.READ_ONLY,
    "workspace_create_branch": SideEffectClass.REMOTE_MUTATION,
    "workspace_delete_branch": SideEffectClass.REMOTE_MUTATION,
    "workspace_self_heal_branch": SideEffectClass.REMOTE_MUTATION,
    # Test-only/sample tool entries
    "schema_test_tool": SideEffectClass.READ_ONLY,
    "sample_tool": SideEffectClass.READ_ONLY,
    # Optional/extra tools
    "ping_extensions": SideEffectClass.READ_ONLY,
    "get_file_slice": SideEffectClass.READ_ONLY,
    "get_file_with_line_numbers": SideEffectClass.READ_ONLY,
    "open_file_context": SideEffectClass.READ_ONLY,
    "delete_file": SideEffectClass.REMOTE_MUTATION,
    "update_file_from_workspace": SideEffectClass.REMOTE_MUTATION,
}


def resolve_side_effect_class(tool_name: str) -> SideEffectClass:
    try:
        return TOOL_SIDE_EFFECTS[tool_name]
    except KeyError as exc:  # pragma: no cover - defensive
        raise KeyError(f"Tool {tool_name!r} is missing a side-effect classification") from exc


def compute_write_action_flag(side_effect: SideEffectClass, *, write_allowed: bool) -> bool:
    """Return whether a tool should be flagged as requiring connector UI approval.

    Policy:
    - READ_ONLY: never prompts.
    - REMOTE_MUTATION ("hard writes"): always prompts.
    - LOCAL_MUTATION: never prompts; enforcement is server-side via the write gate
      and the WRITE_ALLOWED environment toggle.
    """

    if side_effect is SideEffectClass.READ_ONLY:
        return False
    if side_effect is SideEffectClass.REMOTE_MUTATION:
        return True
    # LOCAL_MUTATION
    return False


__all__ = [
    "SideEffectClass",
    "TOOL_SIDE_EFFECTS",
    "compute_write_action_flag",
    "resolve_side_effect_class",
]
