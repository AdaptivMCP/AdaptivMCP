# start_session: GitHub MCP session protocol

This document describes how assistants should start and run sessions when using the GitHub MCP server for this controller repo (Proofgate-Revocations/chatgpt-mcp-github).

## Goals

- Reduce invalid tool calls
- Keep long workflows from getting stuck
- Provide a single protocol that controllers can copy into system prompts

Pair this protocol with the official system prompt in `docs/CONTROLLER_PROMPT_V1.md` and the live `controller_contract` tool so assistants internalize their role as the engineer. `controller_contract` is the single source of truth for contract details; this document and the controller prompt simply describe how to execute that contract in practice. You are expected to run the startup sequence yourself on the very first tool call of a session—never ask the human to run commands or supply diffs for you.
## 1. Startup sequence

At the start of a new conversation, or after context loss, do these tool calls in order:

1. Call `get_server_config` and `validate_environment` to learn write_allowed, default branch, and limits, and to confirm the server is healthy.
2. Call `list_write_tools` once so you know which tools are gated before you try to use them.
3. Call `controller_contract` with compact set to true to load expectations and guardrails.
4. Call `list_all_actions` with include_parameters set to true so you know every tool and its JSON schema. This controller guarantees that each returned tool exposes a non-null `input_schema` object; when an underlying MCP tool does not publish a schema, the server synthesizes a minimal {type: "object", properties: {}} schema so you can still reason about argument shapes.
5. When you encounter a tool you have not already used correctly in this session, call `describe_tool` to inspect its `input_schema`, and use `validate_tool_args` on your planned `args` object before the first real invocation, especially for write-tagged or complex tools.
6. Use `get_repo_dashboard` and `list_repository_tree` on the default branch to understand layout instead of guessing paths.
7. Use `get_latest_branch_status` on the controller default branch (and any active feature branches) to understand ahead/behind state, open PRs, and the most recent workflow result before attempting to "fix" CI.

Treat the results of these tools as the source of truth for the rest of the session, with `controller_contract` as the canonical contract and this document as the execution playbook that must remain consistent with it.## 2. Tool arguments and validation

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

When I (an assistant like Joeys GitHub) am editing this controller repo or any other repository through this MCP server, I follow this pattern:

- I call `get_server_config` once per session to confirm write posture and learn the controller default branch.
- I use `ensure_branch` (or `create_branch`) from the default branch before making edits, and I avoid committing to `main` directly.
- I prefer diff based tools such as `build_unified_diff`, `build_section_based_diff`, and commit helpers instead of rewriting whole files. I reserve full replacements for intentional, small files that are easy to review.
- After applying changes, I use `compare_refs` or `get_branch_summary` to summarize what shifted before opening a PR.
- I keep changes behind pull requests: I prefer `open_pr_for_existing_branch` (or `update_files_and_open_pr`) targeting the default branch unless the user says otherwise.
- I treat `commit_workspace` and `commit_workspace_files` as my defaults for feature branches: commits to non-default branches are allowed even when `WRITE_ALLOWED` is `False`, but writes targeting the controller default branch still require explicit authorization via `authorize_write_actions`.

## 4. Workspace, tests, and editing rules

For more complex or test-sensitive work, and especially when editing code or docs in this controller repo:

- Use `ensure_workspace_clone` on the relevant branch to get a persistent workspace.
- Treat `run_command` as your interactive terminal for *small, focused* commands (listing files, running tests, `grep`, formatters), not as a place to embed large multi-line Python or shell scripts that rewrite files.
- Prefer diff- and section-based tools for file edits instead of hand-rolled inline scripts:
  - Use `update_file_sections_and_commit` or `apply_line_edits_and_commit` for targeted updates to existing files.
  - Use `build_unified_diff` or `build_section_based_diff` together with `apply_patch_and_commit` when you need to stage more complex patches.
- Avoid constructing huge heredocs or multi-line code blobs inside tool arguments (for example `run_command.command`); those patterns are brittle under JSON encoding and often cause control-character errors or disconnections.
- Sync edits back with `update_file_from_workspace`, `commit_workspace_files`, or `commit_workspace` on a feature branch rather than trying to rewrite controller files inline via ad-hoc scripts.
- Keep all workspace actions scoped to the feature branch created via `ensure_branch`, then summarize changes and open a PR when ready.

## 5. Large files and context management

- Default to `open_file_context`, `get_file_slice`, or `get_file_with_line_numbers` when only part of a file is relevant.
- When I know I need the entire contents of a single large GitHub file, I prefer `download_user_content` with a `github:` URL (for example `github:owner/repo:path/to/file[@ref]`) so I can fetch it once into the workspace instead of calling file-slice tools in a loop.
- Use `build_section_based_diff` or `build_unified_diff` for targeted patches instead of full-file rewrites.
- For large searches or cross-repo questions, prefer repo-scoped `search` calls before resorting to global queries.

## 6. Issues, PRs, CI, and rate limits

- For issue or PR tasks, start with `open_issue_context` for issues or `get_pr_overview`/`get_pr_info` for pull requests.
- When you need a normalized issue summary, checklists, and related branches/PRs, call `get_issue_overview` before planning work, then inspect diffs via `list_pr_changed_filenames` and `get_pr_diff`.
- When you need a compact PR summary, changed files, and CI status for a pull request, call `get_pr_overview` before deciding which write tools to use.
- When you know the branch name and want to discover PRs tied to it, call `recent_prs_for_branch` to list open (and optionally recent closed) pull requests for that branch.
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

## 9. Role clarity and branch-first workflows

- You are the developer in this setup. Run the startup checklist yourself, use the tools directly, and never offload edits or command execution to the human.
- Default to the branch-diff-test-PR loop: create or reuse a feature branch with `ensure_branch`, apply changes with diff helpers, run repo-native tests or checks on that branch, and open a PR when the work is ready for review.
- Keep JSON discipline: lean on `list_all_actions`/`describe_tool` to confirm schemas, and use `validate_tool_args` before invoking write or unfamiliar tools so you catch mistakes before execution.
