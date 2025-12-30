# Detailed MCP tools reference

This document provides a concise tool catalog grouped by function.

## Tool catalog (grouped)

### Environment & server

- `validate_environment` — validate GitHub authentication, repo/branch defaults, and permissions.
- `get_server_config` — safe summary of server settings (timeouts, concurrency, git identity).
- `get_rate_limit` — GitHub API rate limiting.
- `get_user_login` — authenticated user.

### Repository & search

- `get_repository` — repository metadata.
- `fetch_url` — fetch an external HTTPS URL.

### Workspace

- `render_shell` — Render-centric shell command that clones from the default branch, optionally creates a new branch, then runs a command in the workspace.
- `terminal_command` — run shell commands in the workspace.

Note: file-content and workspace file management tools are disabled by default in
this deployment to keep all editing and inspection in the shell. Use
`MCP_TOOL_DENYLIST` to override.

### Branches & PRs

- `create_branch` / `ensure_branch` — create branches via GitHub API.
- `workspace_create_branch` / `workspace_delete_branch` — branch ops via git in workspace.
- `get_branch_summary` / `get_latest_branch_status` — ahead/behind + PR/CI snapshot.
- `create_pull_request` — open a PR.
- `open_pr_for_existing_branch` — idempotent PR open/reuse for an existing branch.
- `get_pr_info` / `get_pr_overview` — PR metadata + file/CI summary.
- `list_pr_changed_filenames` — list changed files.
- `comment_on_pull_request` / `close_pull_request` / `merge_pull_request` — PR lifecycle.

### Issues

- `list_recent_issues` / `list_repository_issues` — list issues.
- `fetch_issue` / `fetch_issue_comments` — raw issue + comments.
- `create_issue` / `update_issue` / `comment_on_issue` — issue lifecycle.
- `get_issue_overview` / `open_issue_context` / `resolve_handle` — navigation helpers.

### GitHub Actions

- `list_workflow_runs` / `get_workflow_run` — run metadata.
- `trigger_workflow_dispatch` / `trigger_and_wait_for_workflow` — dispatch workflows.

### Repository creation

- `create_repository` — create a new repo (supports templates and payload overrides to match GitHub’s "New repository" UI).
