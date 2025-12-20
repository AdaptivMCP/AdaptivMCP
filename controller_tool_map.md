# Controller tool map
This file is a **developer-facing index**: where each MCP tool is defined in the codebase.
Line numbers are approximate and may shift; treat them as jump points for navigation.

To discover the live tool surface at runtime, use the tools themselves: `list_all_actions` and `describe_tool`.

---
## Entry tool surface (main.py)
| Tool | File | Line | Notes |
|---|---:|---:|---|
| `authorize_write_actions` | `main.py` | 358 | Allow or block tools marked write_action=True for this server. |
| `get_recent_tool_events` | `main.py` | 374 | Delegates to github_mcp.main_tools.observability.get_recent_tool_events. |
| `get_recent_server_errors` | `main.py` | 386 | Delegates to github_mcp.main_tools.observability.get_recent_server_errors. |
| `get_recent_server_logs` | `main.py` | 398 | Return recent server-side logs captured in memory. |
| `list_render_logs` | `main.py` | 415 |  |
| `get_render_metrics` | `main.py` | 446 |  |
| `get_server_config` | `main.py` | 492 |  |
| `validate_json_string` | `main.py` | 503 |  |
| `get_repo_defaults` | `main.py` | 510 |  |
| `validate_environment` | `main.py` | 519 | Check GitHub-related environment settings and report problems. |
| `pr_smoke_test` | `main.py` | 527 |  |
| `get_rate_limit` | `main.py` | 538 |  |
| `get_user_login` | `main.py` | 545 |  |
| `list_repositories` | `main.py` | 552 |  |
| `list_repositories_by_installation` | `main.py` | 564 |  |
| `create_repository` | `main.py` | 573 |  |
| `list_recent_issues` | `main.py` | 630 |  |
| `list_repository_issues` | `main.py` | 642 |  |
| `fetch_issue` | `main.py` | 663 |  |
| `fetch_issue_comments` | `main.py` | 670 |  |
| `fetch_pr` | `main.py` | 679 |  |
| `get_pr_info` | `main.py` | 686 |  |
| `fetch_pr_comments` | `main.py` | 693 |  |
| `list_pr_changed_filenames` | `main.py` | 702 |  |
| `get_commit_combined_status` | `main.py` | 711 |  |
| `get_issue_comment_reactions` | `main.py` | 718 |  |
| `get_pr_reactions` | `main.py` | 727 | Fetch reactions for a GitHub pull request. |
| `get_pr_review_comment_reactions` | `main.py` | 742 | Fetch reactions for a pull request review comment. |
| `list_write_tools` | `main.py` | 757 | Describe write-capable tools exposed by this server. |
| `get_repository` | `main.py` | 769 | Look up repository metadata (topics, default branch, permissions). |
| `list_branches` | `main.py` | 778 | Enumerate branches for a repository with GitHub-style pagination. |
| `move_file` | `main.py` | 797 |  |
| `get_file_contents` | `main.py` | 812 | Fetch a single file from GitHub and decode base64 to UTF-8 text. |
| `fetch_files` | `main.py` | 824 |  |
| `get_cached_files` | `main.py` | 843 |  |
| `cache_files` | `main.py` | 862 |  |
| `list_repository_tree` | `main.py` | 874 |  |
| `graphql_query` | `main.py` | 897 |  |
| `fetch_url` | `main.py` | 907 |  |
| `web_search` | `main.py` | 920 |  |
| `web_fetch` | `main.py` | 938 |  |
| `search` | `main.py` | 949 |  |
| `download_user_content` | `main.py` | 965 | Download user-provided content (sandbox/local/http) with base64 encoding. |
| `list_workflow_runs` | `main.py` | 996 | List recent GitHub Actions workflow runs with optional filters. |
| `list_recent_failures` | `main.py` | 1013 | List recent failed or cancelled GitHub Actions workflow runs. |
| `list_tools` | `main.py` | 1037 | Lightweight tool catalog. |
| `list_all_actions` | `main.py` | 1049 | Enumerate every available MCP tool with read/write metadata. |
| `describe_tool` | `main.py` | 1077 | Inspect one or more registered MCP tools by name. |
| `validate_tool_args` | `main.py` | 1110 | Validate candidate payload(s) against tool input schemas without running them. |
| `get_workflow_run` | `main.py` | 1148 | Retrieve a specific workflow run including timing and conclusion. |
| `list_workflow_run_jobs` | `main.py` | 1156 | List jobs within a workflow run, useful for troubleshooting failures. |
| `get_workflow_run_overview` | `main.py` | 1169 | Summarize a GitHub Actions workflow run for CI triage. |
| `get_job_logs` | `main.py` | 1187 | Fetch raw logs for a GitHub Actions job without truncation. |
| `wait_for_workflow_run` | `main.py` | 1195 | Poll a workflow run until completion or timeout. |
| `get_issue_overview` | `main.py` | 1216 | Summarize a GitHub issue for navigation and planning. |
| `trigger_workflow_dispatch` | `main.py` | 1229 | Trigger a workflow dispatch event on the given ref. |
| `trigger_and_wait_for_workflow` | `main.py` | 1249 | Trigger a workflow and block until it completes or hits timeout. |
| `list_pull_requests` | `main.py` | 1276 |  |
| `merge_pull_request` | `main.py` | 1292 |  |
| `close_pull_request` | `main.py` | 1311 |  |
| `comment_on_pull_request` | `main.py` | 1318 |  |
| `create_issue` | `main.py` | 1329 | Create a GitHub issue in the given repository. |
| `update_issue` | `main.py` | 1345 | Update fields on an existing GitHub issue. |
| `comment_on_issue` | `main.py` | 1369 | Post a comment on an issue. |
| `open_issue_context` | `main.py` | 1381 | Return an issue plus related branches and pull requests. |
| `resolve_handle` | `main.py` | 1407 |  |
| `create_branch` | `main.py` | 1419 |  |
| `ensure_branch` | `main.py` | 1430 |  |
| `get_branch_summary` | `main.py` | 1441 |  |
| `get_latest_branch_status` | `main.py` | 1448 |  |
| `get_repo_dashboard` | `main.py` | 1457 | Return a compact, multi-signal dashboard for a repository. |
| `create_pull_request` | `main.py` | 1517 | Open a pull request from ``head`` into ``base``. |
| `open_pr_for_existing_branch` | `main.py` | 1539 | Open a pull request for an existing branch into a base branch. |
| `update_files_and_open_pr` | `main.py` | 1563 | Commit multiple files, verify each, then open a PR in one call. |
| `create_file` | `main.py` | 1587 |  |
| `apply_text_update_and_commit` | `main.py` | 1603 |  |
| `get_pr_overview` | `main.py` | 1628 |  |
| `recent_prs_for_branch` | `main.py` | 1643 |  |

## Workspace tools (github_mcp/workspace_tools)
| Tool | File | Line | Notes |
|---|---:|---:|---|
| `ensure_workspace_clone` | `github_mcp/workspace_tools/clone.py` | 23 | Ensure a persistent workspace clone exists for a repo/ref. |
| `terminal_command` | `github_mcp/workspace_tools/commands.py` | 26 | Run a shell command inside the repo workspace and return its result. |
| `commit_workspace` | `github_mcp/workspace_tools/commit.py` | 260 | Commit workspace changes and optionally push them. |
| `commit_workspace_files` | `github_mcp/workspace_tools/commit.py` | 395 | Commit and optionally push specific files from the persistent workspace. |
| `get_workspace_changes_summary` | `github_mcp/workspace_tools/commit.py` | 536 | Summarize modified, added, deleted, renamed, and untracked files in the workspace. |
| `build_pr_summary` | `github_mcp/workspace_tools/commit.py` | 624 | Build a normalized JSON summary for a pull request description. |
| `get_workspace_file_contents` | `github_mcp/workspace_tools/fs.py` | 103 | Read a file from the persistent workspace clone (no shell). |
| `set_workspace_file_contents` | `github_mcp/workspace_tools/fs.py` | 129 | Replace a workspace file's contents by writing the full file text. |
| `workspace_create_branch` | `github_mcp/workspace_tools/git_ops.py` | 35 | Create a branch using the workspace (git), optionally pushing to origin. |
| `workspace_delete_branch` | `github_mcp/workspace_tools/git_ops.py` | 108 | Delete a non-default branch using the workspace clone. |
| `workspace_self_heal_branch` | `github_mcp/workspace_tools/git_ops.py` | 194 | Detect a mangled workspace branch and recover to a fresh branch. |
| `list_workspace_files` | `github_mcp/workspace_tools/listing.py` | 24 | List files in the workspace clone (bounded, no shell). |
| `search_workspace` | `github_mcp/workspace_tools/listing.py` | 125 | Search text files in the workspace clone (bounded, no shell). |
| `run_tests` | `github_mcp/workspace_tools/suites.py` | 28 | Run the project's test command in the persistent workspace and summarize the result. |
| `run_quality_suite` | `github_mcp/workspace_tools/suites.py` | 108 | Run the standard quality/test suite for a repo/ref. |
| `run_lint_suite` | `github_mcp/workspace_tools/suites.py` | 212 | Run the lint or static-analysis command in the workspace. |

