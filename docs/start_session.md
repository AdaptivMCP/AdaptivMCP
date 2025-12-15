
- Full-file replacements are preferred: edit with `terminal_command` (workspace) or set `updated_content` and commit with `apply_text_update_and_commit`.
- `terminal_command` was previously named `run_command`; `run_command` remains available as a deprecated alias.
- Avoid diff/patch tools; Git commits already provide diffs in GitHub.
# Getting started with the GitHub MCP server

This document explains how controllers and assistants should start a session with the GitHub MCP server in this repository.

These docs are the source of truth for expectations and constraints. The server does **not** add its own per-task budgets beyond the constraints imposed by the host environment (for example ChatGPT/OpenAI) and GitHub; instead, it defines workflows, guardrails, and editing preferences that operate within whatever constraints the environment enforces.

## Recommended startup sequence

On a new session (or after the context is obviously truncated), controllers should guide assistants to run these tools in order instead of guessing configuration or schemas. Assistants should not ask humans to run these commands for them.

1. `get_server_config`
   - Discover whether writes are allowed (`write_allowed`).
   - Learn the default controller repository and branch.
   - Inspect HTTP, concurrency, and approval settings so you understand the environment and its external constraints.

2. `list_all_actions` with `include_parameters=true`
   - Enumerate every MCP tool exposed by this server.
   - See which tools are read-only versus write-tagged.
   - Inspect top-level input schemas for each tool.

3. For each tool you plan to use in this session (especially write-tagged or complex ones):
   - Call `describe_tool` with that tool's name and `include_parameters=true` to see its current input schema.
   - Prepare the arguments as a real JSON object (no JSON-in-strings).
   - Call `validate_tool_args` with your planned arguments.
   - Only call the real tool when `validate_tool_args` reports `valid=true`.

You may cache the results of these calls for the rest of the conversation instead of re-deriving them by hand.

## Large files, diffs, and "large payloads"

Controllers should encourage assistants to work with slices and diffs instead of huge blobs of text or logs. In this repo, "large payloads" refers to patterns like:

- Sending entire repositories or very large files as a single argument to a tool.
- Returning massive command output when a filtered or truncated view is enough.
- Embedding giant multi-line scripts, heredocs, or concatenated logs in a single tool call or response.

Instead, assistants should:

- Use `get_file_slice` or `get_file_with_line_numbers` to fetch only the relevant portion of a file.
- Use `terminal_command` for small, focused commands (`rg`, `grep`, `sed -n 'start,endp'`, formatters, tests) and limit output size with flags such as `head` or explicit line ranges.

This keeps responses compact, reduces the risk of truncation or client crashes, and makes PR reviews easier, without requiring assistants to micromanage context windows.

## Branches, workspaces, and PRs (controller summary)

Controllers should keep the branch and workspace rules visible in their prompts. In short:

- Do not work directly on the default branch for feature work. Use `ensure_branch` or `create_branch` to create a feature branch from the default branch and treat that as your effective main for the task.
- Use `ensure_workspace_clone` to create or refresh a persistent workspace for the controller repo and branch you are working on.
- Use `terminal_command` in that workspace for tests, linters, and small inspection commands.
- Use `commit_workspace` or `commit_workspace_files` to push changes from the workspace back to the feature branch. After pushing, reclone the workspace with `ensure_workspace_clone(..., reset=true)` before further validation (tests, lint, or PR helpers).
- Before opening a PR, run appropriate tests and linters from a fresh workspace clone of the feature branch and fix failures by updating code, tests, and docs.
- Use `build_pr_summary` to construct a structured title/body (including `tests_status` and `lint_status` when available), then pass those fields to `open_pr_for_existing_branch` or `update_files_and_open_pr` so PR descriptions stay consistent.

For more detailed behavior and examples, see `docs/assistant/ASSISTANT_HANDOFF.md` and `docs/assistant/CONTROLLER_PROMPT_V1.md`.
