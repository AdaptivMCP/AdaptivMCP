# start_session: GitHub MCP session protocol

This document describes how assistants should start and run sessions when using the GitHub MCP server for this controller repo (Proofgate-Revocations/chatgpt-mcp-github).

## Goals

- Reduce invalid tool calls
- Keep long workflows from getting stuck
- Provide a single protocol that controllers can copy into system prompts

## 1. Startup sequence

At the start of a new conversation, or after context loss, do these tool calls in order:

1. Call `get_server_config` and `validate_environment` to learn write_allowed, default branch, and limits, and to confirm the server is healthy.
2. Call `list_write_tools` once so you know which tools are gated before you try to use them.
3. Call `controller_contract` with compact set to true to load expectations and guardrails.
4. Call `list_all_actions` with include_parameters set to true so you know every tool and its JSON schema.
5. When you encounter a tool you have not already used correctly in this session, call `describe_tool` (and optionally `validate_tool_args`) before the first real invocation.
6. Use `get_repo_dashboard` and `list_repository_tree` on the default branch to understand layout instead of guessing paths.

Treat the results of these tools as the source of truth for the rest of the session.

## 2. Tool arguments and validation

- Follow each tool's declared parameter schema exactly.
- Build arguments as literal JSON objects, not strings containing JSON.
- Do not invent parameters that are not documented in `list_all_actions`.

Before using a write tool, or a tool you have not called yet in this conversation:

1. Prepare the arguments you plan to use.
2. Call `validate_tool_args` with the tool name and those arguments.
3. Only call the real tool when validation reports valid is true.

If a tool call fails because of argument or schema errors:

- Stop guessing.
- Re-read the tool definition from `list_all_actions`.
- Fix the payload and re-run `validate_tool_args` before trying again.

## 3. Editing, branches, and pull requests

- Check `get_server_config` to confirm that write actions are allowed.
- Use `ensure_branch` (or `create_branch`) from the default branch before making edits. Avoid committing to `main` directly.
- Prefer diff based tools such as `build_unified_diff`, `build_section_based_diff`, and commit helpers instead of rewriting whole files. Reserve full replacements for intentional, small files.
- After applying changes, use `compare_refs` or `get_branch_summary` to summarize what shifted before opening a PR.
- Keep changes behind pull requests: prefer `open_pr_for_existing_branch` (or `update_files_and_open_pr`) targeting the default branch unless the user says otherwise.

## 4. Workspace and tests

For more complex or test-sensitive work:

- Use `ensure_workspace_clone` on the relevant branch to get a persistent workspace.
- Run `run_command` for repo-specific tools (linters, formatters, utility scripts) and `run_tests` for the main test suite before opening a PR.
- Sync edits back with `update_file_from_workspace`, `commit_workspace_files`, or `commit_workspace` rather than trying to rewrite files inline.
- Keep all workspace actions scoped to the feature branch created via `ensure_branch`.

## 5. Large files and context management

- Default to `open_file_context`, `get_file_slice`, or `get_file_with_line_numbers` when only part of a file is relevant.
- Use `build_section_based_diff` or `build_unified_diff` for targeted patches instead of full-file rewrites.
- For large searches or cross-repo questions, prefer repo-scoped `search` calls before resorting to global queries.

## 6. Issues, PRs, CI, and rate limits

- For issue or PR tasks, start with `open_issue_context` or `fetch_pr`/`get_pr_info`, then inspect diffs via `list_pr_changed_filenames` and `get_pr_diff`.
- When diagnosing CI, use `list_workflow_runs`, `get_workflow_run`, `list_workflow_run_jobs`, and `get_job_logs` instead of guessing. Use `trigger_workflow_dispatch` or `trigger_and_wait_for_workflow` only when asked.
- Check `get_rate_limit` before heavy searches or bulk operations. Use `resolve_handle` to expand shorthand references before acting on them.

## 7. Long workflows

For non trivial tasks:

- Write a short numbered plan.
- Execute a few steps at a time.
- After each batch of work, summarize what changed and what is next.

If you see repeated failures on the same operation:

- After two failed tool calls, stop retrying.
- Re-check the schema and use `validate_tool_args`.
- If you still cannot progress, explain the blocker to the user instead of looping.

## 8. Interaction with the user

- Do not ask the user to run shell commands or apply patches by hand.
- Clearly state which files, branches, and tools you used.
- When you open a pull request, include what changed, why, and how it was tested.