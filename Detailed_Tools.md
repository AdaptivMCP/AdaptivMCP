# Tool reference (developer-facing)

This document is a human-friendly index of the MCP tool surface exposed by this server.

**Source of truth:** the runtime tools `list_all_actions` and `describe_tool`.

Tool names are stable; schemas may evolve. When in doubt, call `describe_tool`.

---

## Logging contract (user-facing)

- Log lines are meant to read like an assistant talking to a user.
- `CHAT` / `INFO` should answer: *what is happening, why, and what happens next*.
- `DETAILED` can include diffs, command output, and deep context.
- Avoid leaking internal IDs, raw JSON blobs, stack traces, or token-like data into user-facing logs.

## Server + tool introspection

| Tool | Summary |
|---|---|
| `get_server_config` | GET Server Config. |
| `validate_environment` | Check GitHub-related environment settings and report problems. |
| `list_tools` | List available MCP tools with basic read/write metadata. Use describe_tool (or list_all_actions with include_parameters=true) when you need full schemas. |
| `list_all_actions` | Enumerate every available MCP tool with read/write metadata. |
| `describe_tool` | Return metadata and optional schema for one or more tools. Prefer this over manually scanning list_all_actions in long sessions. |
| `validate_tool_args` | Validate candidate payload(s) against tool input schemas without running them. |
| `validate_json_string` | Validate a JSON string and return a normalized form. |
| `get_rate_limit` | GET Rate Limit. |
| `ping_extensions` | Ping the MCP server extensions surface. |

## Write gate

| Tool | Summary |
|---|---|
| `authorize_write_actions` | Allow or block tools marked write_action=True for this server. |
| `list_write_tools` | Describe write-capable tools exposed by this server. |

## GitHub: repositories + browsing

| Tool | Summary |
|---|---|
| `get_repository` | Look up repository metadata (topics, default branch, permissions). |
| `get_repo_defaults` | GET Repo Defaults. |
| `get_repo_dashboard` | Return a compact, multi-signal dashboard for a repository. |
| `list_repositories` | List Repositories. |
| `list_repositories_by_installation` | List Repositories BY Installation. |
| `list_branches` | Enumerate branches for a repository with GitHub-style pagination. |
| `get_branch_summary` | GET Branch Summary. |
| `get_latest_branch_status` | GET Latest Branch Status. |
| `get_commit_combined_status` | GET Commit Combined Status. |
| `list_repository_tree` | List Repository Tree. |
| `list_repository_issues` | List Repository Issues. |
| `list_recent_issues` | List Recent Issues. |
| `get_user_login` | GET User Login. |

## GitHub: files (read)

| Tool | Summary |
|---|---|
| `get_file_contents` | Fetch a single file from GitHub and decode base64 to UTF-8 text. |
| `get_file_slice` | Return a citation-friendly slice of a file. |
| `get_file_with_line_numbers` | Render a compact, line-numbered view of a file to simplify manual edits. |
| `open_file_context` | Return a citation-friendly slice of a file with line numbers and content entries. |
| `fetch_files` | Fetch Files. |
| `get_cached_files` | Return cached file payloads for a repository/ref without re-fetching from GitHub. Entries persist for the lifetime of the server process until evicted by size or entry caps. |
| `cache_files` | Fetch one or more files and persist them in the server-side cache so assistants can recall them without repeating GitHub reads. Use refresh=true to bypass existing cache entries. |

## GitHub: files (write)

| Tool | Summary |
|---|---|
| `create_file` | Create File. |
| `delete_file` | Delete a file from a GitHub repository using the Contents API. Use ensure_branch if you want to delete on a dedicated branch. |
| `move_file` | Move File. |
| `update_files_and_open_pr` | Commit multiple files, verify each, then open a PR in one call. |
| `apply_text_update_and_commit` | Apply Text Update AND Commit. |
| `update_file_from_workspace` | Update a single file in a GitHub repository from the persistent workspace checkout. Use terminal_command to edit the workspace file first, then call this tool to sync it back to the branch. |

## GitHub: branches

| Tool | Summary |
|---|---|
| `create_branch` | Create Branch. |
| `ensure_branch` | Ensure Branch. |
| `recent_prs_for_branch` | Return recent pull requests associated with a branch, grouped by state. |
| `workspace_create_branch` | Create a branch using the workspace (git), optionally pushing to origin. |
| `workspace_delete_branch` | Delete a non-default branch using the workspace clone. |
| `workspace_self_heal_branch` | Detect a mangled workspace branch and recover to a fresh branch. |

## GitHub: issues

| Tool | Summary |
|---|---|
| `create_issue` | Create a GitHub issue in the given repository. |
| `fetch_issue` | Fetch Issue. |
| `fetch_issue_comments` | Fetch Issue Comments. |
| `open_issue_context` | Return an issue plus related branches and pull requests. |
| `update_issue` | Update fields on an existing GitHub issue. |
| `comment_on_issue` | Post a comment on an issue. |
| `get_issue_overview` | Return a high-level overview of an issue, including related branches, pull requests, and checklist items, so assistants can decide what to do next. |
| `get_issue_comment_reactions` | GET Issue Comment Reactions. |

## GitHub: pull requests

| Tool | Summary |
|---|---|
| `create_pull_request` | Open a pull request from ``head`` into ``base``. |
| `open_pr_for_existing_branch` | Open a pull request for an existing branch into a base branch. |
| `fetch_pr` | Fetch PR. |
| `fetch_pr_comments` | Fetch PR Comments. |
| `comment_on_pull_request` | Comment ON Pull Request. |
| `get_pr_info` | GET PR Info. |
| `get_pr_overview` | Return a compact overview of a pull request, including files and CI status. |
| `list_pull_requests` | List Pull Requests. |
| `list_pr_changed_filenames` | List PR Changed Filenames. |
| `merge_pull_request` | Merge Pull Request. |
| `close_pull_request` | Close Pull Request. |
| `get_pr_reactions` | Fetch reactions for a GitHub pull request. |
| `get_pr_review_comment_reactions` | Fetch reactions for a pull request review comment. |
| `build_pr_summary` | Build a normalized JSON summary for a pull request description. |

## GitHub Actions

| Tool | Summary |
|---|---|
| `list_workflow_runs` | List recent GitHub Actions workflow runs with optional filters. |
| `get_workflow_run` | Retrieve a specific workflow run including timing and conclusion. |
| `get_workflow_run_overview` | Summarize a GitHub Actions workflow run for CI triage. |
| `list_workflow_run_jobs` | List jobs within a workflow run, useful for troubleshooting failures. |
| `get_job_logs` | Fetch raw logs for a GitHub Actions job without truncation. |
| `list_recent_failures` | List recent failed or cancelled GitHub Actions workflow runs. |
| `trigger_workflow_dispatch` | Trigger a workflow dispatch event on the given ref. |
| `trigger_and_wait_for_workflow` | Trigger a workflow and block until it completes or hits timeout. |
| `wait_for_workflow_run` | Poll a workflow run until completion or timeout. |

## Workspace: clone + inspection

| Tool | Summary |
|---|---|
| `ensure_workspace_clone` | Ensure a persistent workspace clone exists for a repo/ref. |
| `list_workspace_files` | List files in the workspace clone (bounded, no shell). |
| `search_workspace` | Search text files in the workspace clone (bounded, no shell). |
| `get_workspace_file_contents` | Read a file from the persistent workspace clone (no shell). |
| `get_workspace_changes_summary` | Summarize modified, added, deleted, renamed, and untracked files in the workspace. |

## Workspace: write + git

| Tool | Summary |
|---|---|
| `set_workspace_file_contents` | Replace a workspace file's contents by writing the full file text. |
| `terminal_command` | Run a shell command inside the repo workspace and return its result. |
| `commit_workspace` | Commit workspace changes and optionally push them. |
| `commit_workspace_files` | Commit and optionally push specific files from the persistent workspace. |

## Workspace: quality suites

| Tool | Summary |
|---|---|
| `run_tests` | Run the project's test command in the persistent workspace and summarize the result. |
| `run_lint_suite` | Run the lint or static-analysis command in the workspace. |
| `run_quality_suite` | Run the standard quality/test suite for a repo/ref. |

## Render

| Tool | Summary |
|---|---|
| `list_render_logs` | Fetch recent logs from Render (requires RENDER_API_KEY). Render /logs requires ownerId; pass ownerId or set RENDER_OWNER_ID; otherwise the tool will attempt to resolve it from the service id. |
| `get_render_metrics` | Fetch basic Render service metrics (defaults to RENDER_SERVICE_ID when resourceId is omitted; requires RENDER_API_KEY). |

## Web browser

| Tool | Summary |
|---|---|
| `web_search` | Search the public web (DuckDuckGo HTML endpoint) and return titles, URLs, and snippets. |
| `web_fetch` | Fetch a public web URL with conservative safety checks and optional HTML-to-text extraction. |
| `fetch_url` | Fetch URL. |

## Utilities

| Tool | Summary |
|---|---|
| `download_user_content` | Download user-provided content (sandbox/local/http) with base64 encoding. |
| `resolve_handle` | Resolve Handle. |
| `search` | Search. |
| `graphql_query` | Graphql Query. |
| `create_repository` | Create Repository. |
| `pr_smoke_test` | PR Smoke Test. |

## In-memory logs + diagnostics

| Tool | Summary |
|---|---|
| `get_recent_tool_events` | List recent tool invocation events captured in memory. |
| `get_recent_server_logs` | Return recent server-side logs captured in memory (useful when provider logs are unavailable). |
| `get_recent_server_errors` | List recent server-side errors captured in memory. |

---

## Notes on compatibility aliases

- The workspace shell entrypoint is `terminal_command`.
- `fetch_url` is a compatibility wrapper; prefer `web_fetch` for internet access.
