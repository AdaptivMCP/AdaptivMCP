# Controller Tool Map

This document lists all MCP tools exposed by the `chatgpt-mcp-github` controller,
with their defining module, starting line number (as of this commit), and a
short description of what each tool does.

> NOTE: Line numbers are approximate and will drift as the code evolves. When
> updating tools, please update this map in the same PR so it remains useful
> for quick navigation and debugging.

## Legend

- **Tool name**: The MCP tool name (function name).
- **Module**: The Python module where the tool is defined.
- **Line**: 1-based line number where the tool's `@mcp_tool` definition starts.
- **Summary**: A short, user-facing description derived from the tool docstring.

## Top-level controller tools (`main.py`)

| Tool name | Module | Line | Summary |
| --- | --- | --- | --- |
| `authorize_write_actions` | `main.py` | 226 | Allow or block tools marked `write_action=True` for this server. |
| `get_server_config` | `main.py` | 239 | Return a safe summary of MCP connector and runtime settings. |
| `validate_json_string` | `main.py` | 294 | Validate a JSON string and report parse status and errors. |
| `get_repo_defaults` | `main.py` | 346 | Return default configuration for a GitHub repository. |
| `validate_environment` | `main.py` | 374 | Check GitHub-related environment settings and report problems. |
| `pr_smoke_test` | `main.py` | 642 | Create a trivial branch with a one-line change and open a draft PR. |
| `get_rate_limit` | `main.py` | 710 | Return the authenticated token's GitHub rate-limit document. |
| `get_user_login` | `main.py` | 716 | Return the login for the authenticated GitHub user. |
| `list_repositories` | `main.py` | 731 | List repositories accessible to the authenticated user. |
| `list_repositories_by_installation` | `main.py` | 748 | List repositories accessible via a specific GitHub App installation. |
| `list_recent_issues` | `main.py` | 760 | Return recent issues the user can access (includes PRs). |
| `list_repository_issues` | `main.py` | 773 | List issues for a specific repository (includes PRs). |
| `fetch_issue` | `main.py` | 793 | Fetch a GitHub issue. |
| `fetch_issue_comments` | `main.py` | 800 | Fetch comments for a GitHub issue. |
| `fetch_pr` | `main.py` | 814 | Fetch pull request details. |
| `get_pr_info` | `main.py` | 821 | Get metadata for a pull request without downloading the diff. |
| `fetch_pr_comments` | `main.py` | 842 | Fetch issue-style comments for a pull request. |
| `list_pr_changed_filenames` | `main.py` | 878 | List files changed in a pull request. |
| `get_commit_combined_status` | `main.py` | 890 | Get combined status for a commit or ref. |
| `get_issue_comment_reactions` | `main.py` | 897 | Fetch reactions for an issue comment. |
| `get_pr_reactions` | `main.py` | 912 | Fetch reactions for a GitHub pull request. |
| `get_pr_review_comment_reactions` | `main.py` | 927 | Fetch reactions for a pull request review comment. |
| `list_write_tools` | `main.py` | 942 | Describe write-capable tools exposed by this server. |
| `get_repository` | `main.py` | 1070 | Look up repository metadata (topics, default branch, permissions). |
| `list_branches` | `main.py` | 1079 | Enumerate branches for a repository with GitHub-style pagination. |
| `move_file` | `main.py` | 1098 | Move or rename a file within a repository on a single branch. |
| `get_file_contents` | `main.py` | 1175 | Fetch a single file from GitHub and decode base64 to UTF-8 text. |
| `fetch_files` | `main.py` | 1187 | Fetch multiple files concurrently with per-file error isolation. |
| `get_cached_files` | `main.py` | 1230 | Return cached file entries and list any missing paths. |
| `cache_files` | `main.py` | 1260 | Fetch files and store them in the in-process cache. |
| `build_unified_diff` | `main.py` | 1303 | Generate a unified diff for a file against proposed new content. |
| `list_repository_tree` | `main.py` | 1373 | List files and folders in a repository tree with optional filtering. |
| `graphql_query` | `main.py` | 1462 | Execute a GitHub GraphQL query using the shared HTTP client and logging wrapper. |
| `fetch_url` | `main.py` | 1478 | Fetch an arbitrary HTTP/HTTPS URL via the shared external client. |
| `search` | `main.py` | 1500 | Perform GitHub search queries (code, repos, issues, commits, or users). |
| `download_user_content` | `main.py` | 1530 | Download user-provided content (sandbox/local/http) with base64 encoding. |
| `list_workflow_runs` | `main.py` | 1554 | List recent GitHub Actions workflow runs with optional filters. |
| `list_recent_failures` | `main.py` | 1586 | List recent failed or cancelled GitHub Actions workflow runs. |
| `list_all_actions` | `main.py` | 1666 | Enumerate every available MCP tool with read/write metadata. |
| `describe_tool` | `main.py` | 1763 | Inspect one or more registered MCP tools by name. |
| `validate_tool_args` | `main.py` | 1902 | Validate candidate payload(s) against tool input schemas without running them. |
| `get_workflow_run` | `main.py` | 2007 | Retrieve a specific workflow run including timing and conclusion. |
| `list_workflow_run_jobs` | `main.py` | 2016 | List jobs within a workflow run, useful for troubleshooting failures. |
| `get_workflow_run_overview` | `main.py` | 2040 | Summarize a GitHub Actions workflow run for CI triage. |
| `get_job_logs` | `main.py` | 2214 | Fetch raw logs for a GitHub Actions job without truncation. |
| `wait_for_workflow_run` | `main.py` | 2241 | Poll a workflow run until completion or timeout. |
| `get_issue_overview` | `main.py` | 2300 | Summarize a GitHub issue for navigation and planning. |
| `trigger_workflow_dispatch` | `main.py` | 2410 | Trigger a workflow dispatch event on the given ref. |
| `trigger_and_wait_for_workflow` | `main.py` | 2453 | Trigger a workflow and block until it completes or hits timeout. |
| `list_pull_requests` | `main.py` | 2503 | List pull requests with optional head/base filters. |
| `merge_pull_request` | `main.py` | 2539 | Merge a pull request using squash (default), merge, or rebase. |
| `close_pull_request` | `main.py` | 2572 | Close a pull request without merging. |
| `comment_on_pull_request` | `main.py` | 2584 | Post a comment on a pull request (issue API under the hood). |
| `create_issue` | `main.py` | 2600 | Create a GitHub issue. |
| `update_issue` | `main.py` | 2630 | Update fields on an existing GitHub issue. |
| `comment_on_issue` | `main.py` | 2672 | Post a comment on an issue. |
| `open_issue_context` | `main.py` | 2692 | Return an issue plus related branches and pull requests. |
| `resolve_handle` | `main.py` | 2850 | Resolve a lightweight GitHub handle into issue, PR, or branch details. |
| `create_branch` | `main.py` | 2965 | Create a new branch from an existing ref (default `main`). |
| `ensure_branch` | `main.py` | 2983 | Idempotently ensure a branch exists, creating it from `from_ref`. |
| `get_branch_summary` | `main.py` | 3002 | Return ahead/behind data, PRs, and latest workflow run for a branch. |
| `get_latest_branch_status` | `main.py` | 3059 | Return a normalized view of the latest status for a branch. |
| `get_repo_dashboard` | `main.py` | 3088 | Return a compact, multi-signal dashboard for a repository. |
| `create_pull_request` | `main.py` | 3239 | Open a pull request from `head` into `base`. |
| `open_pr_for_existing_branch` | `main.py` | 3278 | Open a pull request for an existing branch into a base branch. |
| `update_files_and_open_pr` | `main.py` | 3366 | Commit multiple files, verify each, then open a PR in one call. |
| `create_file` | `main.py` | 3496 | Create a new text file in a repository after normalizing path and branch. |
| `apply_text_update_and_commit` | `main.py` | 3596 | Apply a text update to a single file on a branch, then verify it. |
| `apply_patch_and_commit` | `main.py` | 3738 | Apply a unified diff to a single file, commit it, then verify it. |
| `get_pr_overview` | `main.py` | 4065 | Return a structured summary of a pull request for review and triage. |
| `recent_prs_for_branch` | `main.py` | 4174 | List recent PRs that appear related to a branch. |

## Workspace tools (`github_mcp/tools_workspace.py`)

| Tool name | Module | Line | Summary |
| --- | --- | --- | --- |
| `ensure_workspace_clone` | `github_mcp/tools_workspace.py` | 41 | Ensure a persistent workspace clone exists for a repo/ref. |
| `terminal_command` | `github_mcp/tools_workspace.py` | 67 | Run a shell command inside the repo workspace and return its result. |
| `commit_workspace` | `github_mcp/tools_workspace.py` | 124 | Commit workspace changes and optionally push them. |
| `commit_workspace_files` | `github_mcp/tools_workspace.py` | 181 | Commit and optionally push specific files from the persistent workspace. |
| `get_workspace_changes_summary` | `github_mcp/tools_workspace.py` | 241 | Summarize modified, added, deleted, renamed, and untracked files in the workspace. |
| `run_tests` | `github_mcp/tools_workspace.py` | 329 | Run the project's test command in the persistent workspace and summarize the result. |
| `run_quality_suite` | `github_mcp/tools_workspace.py` | 407 | Run the standard quality/test suite for a repo/ref. |
| `run_lint_suite` | `github_mcp/tools_workspace.py` | 455 | Run the lint or static-analysis command in the workspace. |
| `build_pr_summary` | `github_mcp/tools_workspace.py` | 531 | Build a normalized JSON summary for a pull request description. |
