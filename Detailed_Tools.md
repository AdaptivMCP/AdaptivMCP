# Detailed MCP tools reference

This document explains how to use the `chatgpt-mcp-github` MCP server tools together in real workflows.

## Editing policy (important)

- **Preferred edit style:** full-file replacement.
  - Use **workspace editing** (`set_workspace_file_contents` + `commit_workspace_files`) or **GitHub commit helper** (`apply_text_update_and_commit`).
- **Diff/patch editing is discouraged:** `apply_patch_and_commit` exists only for rare cases where a full replacement is impractical.
- **Diffs are still useful for information:** PR review (`get_pr_overview`, GitHub UI) and previews (`build_unified_diff`) are allowed.

## Quick tool discovery

- `list_tools` → quick list of tools + read/write flags.
- `describe_tool` / `validate_tool_args` → schemas and safe preflight.

## Recommended workflows

### 1) Standard file change (full replacement)

1. Create or reuse a branch:
   - `ensure_branch` (or workspace equivalent: `workspace_create_branch`).
2. Read the file (avoid huge payloads):
   - `open_file_context` / `get_file_with_line_numbers` / `get_file_contents`.
3. Replace the file:
   - Workspace path (preferred for multi-file edits): `set_workspace_file_contents`.
   - Single-file GitHub helper: `apply_text_update_and_commit`.
4. Validate:
   - `run_quality_suite` (or `run_lint_suite` + `run_tests`).
5. Open or reuse PR:
   - `open_pr_for_existing_branch` (idempotent) or `update_files_and_open_pr`.

### 2) Workspace-heavy change (refactor / formatting)

1. `ensure_workspace_clone`
2. Run commands as if on a local machine:
   - `terminal_command` (note: `run_command` is a deprecated alias)
3. Inspect what changed:
   - `get_workspace_changes_summary`
4. Commit:
   - `commit_workspace` or `commit_workspace_files`
5. Validate and open PR:
   - `run_quality_suite` → `open_pr_for_existing_branch`

### 3) Self-heal a mangled workspace branch

If the workspace clone is in a bad state (wrong branch, conflicts, half-merge, etc.), use:

- `workspace_self_heal_branch`

It can reset to `main`, optionally delete the mangled branch, create a fresh branch, and return plain-language step logs for UI rendering.

### 4) CI triage

- Find runs: `list_workflow_runs` / `list_recent_failures`
- Summarize a run: `get_workflow_run_overview`
- Drill into jobs: `list_workflow_run_jobs` → `get_job_logs`
- Wait for completion: `wait_for_workflow_run`

### 5) Plain-language tool logs for UI / debugging

- `get_recent_tool_events` → recent tool calls (success + failure)
- `get_recent_server_errors` → recent failed tool-call error records

## Tool catalog (grouped)

### Environment & server

- `validate_environment` — validate GitHub token, repo/branch defaults, and permissions.
- `get_server_config` — safe summary of server settings (timeouts, concurrency, git identity).
- `get_rate_limit` — GitHub API rate limits.
- `get_user_login` — authenticated user.

### Repository & search

- `get_repository` — repository metadata.
- `list_repository_tree` — server-side tree listing.
- `search` — GitHub search (code/issues/commits/users/etc.).
- `fetch_url` — fetch an external HTTPS URL.

### Workspace

- `ensure_workspace_clone` — persistent clone for a repo/ref.
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

---

## Notes

- When unsure about write safety or parameter shapes: use `validate_tool_args` then `describe_tool`.
- Prefer `run_quality_suite` before opening a PR so CI failures are caught early.
