# Detailed MCP tools reference

This document explains how to use the MCP server tools.

## Recommended workflows

### 1) Anything related to making Github changes that requires repo info / data, editing files / commit / push

- Use render_shell
- Use API calls only for information the user asks for

### 2) Plain-language tool logs for UI / debugging

- `get_recent_tool_events` → recent tool calls (success + failure)
- `get_recent_server_errors` → recent failed tool-call error records

## Tool catalog (grouped)

### Environment & server

- `validate_environment` — validate GitHub authentication, repo/branch defaults, and permissions.
- `get_server_config` — safe summary of server settings (timeouts, concurrency, git identity).
- `get_rate_limit` — GitHub API rate limiting.
- `get_user_login` — authenticated user.

### Repository & search

- `get_repository` — repository metadata.
- `list_repository_tree` — server-side tree listing.
- `search` — GitHub search (code/issues/commits/users/etc.).
- `fetch_url` — fetch an external HTTPS URL.

### Workspace

- `ensure_workspace_clone` — persistent clone for a repo/ref.
- `render_shell` — Render-centric shell command that clones from the default branch, optionally creates a new branch, then runs a command in the workspace.
- `terminal_command` — run shell commands in the workspace.
- `get_workspace_file_contents` — read a file from the workspace.
- `set_workspace_file_contents` — write a file (full replacement) in the workspace.
- `get_workspace_changes_summary` — summarize workspace changes.
- `commit_workspace` / `commit_workspace_files` — commit workspace changes.

### Files (GitHub API)

- `get_file_contents` / `fetch_files` — fetch file(s) from GitHub.
- `create_file` — create a new file.
- `apply_text_update_and_commit` — update a file by replacing full contents.
- `apply_patch_and_commit` — apply a unified diff patch (discouraged for normal editing).
- `move_file` — rename/move a path.
- `delete_file` — delete a file.
- `update_file_from_workspace` — push a workspace-edited file back to GitHub.

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

