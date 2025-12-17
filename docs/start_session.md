# Getting started with the GitHub MCP server

This document explains how controllers and assistants should start a session with the GitHub MCP server in this repository.

These docs are the source of truth for expectations and constraints.

## Editing preferences

- Full-file replacements are preferred: edit with `terminal_command` (workspace) or set `updated_content` and commit with `apply_text_update_and_commit`.
- `terminal_command` was previously named `run_command`; `run_command` remains available as a deprecated alias.
- Avoid embedding large patch scripts inside JSON strings. If you need complex edits, do them in the workspace and commit normally.

## Recommended startup sequence

On a new session (or after context is obviously truncated), controllers should guide assistants to run these tools in order instead of guessing configuration or schemas. Assistants should not ask humans to run these commands for them.

1. `get_server_config`
   - Discover whether writes are allowed (`write_allowed`) and whether write actions are auto-approved.
   - Learn the default controller repository and branch.

2. `validate_environment`
   - Confirms the controller repo/branch are reachable.
   - Flags missing tokens, misconfigured defaults, and common deployment problems.

3. `list_all_actions(include_parameters=true)`
   - Enumerate every MCP tool exposed by this server.
   - Inspect which tools are read-only vs write-tagged.

4. For any tool you plan to use (especially write-tagged tools):
   - `describe_tool(name=..., include_parameters=true)`
   - `validate_tool_args(tool_name=..., args=...)`

If the session is on Render and you expect deploy/log visibility:

- Confirm Render tools are registered (`list_all_actions`) and configured (`validate_environment`).
- Use `list_render_logs` to validate the server is writing user-facing logs.

## Observability: logs should read like an assistant

Render logs are intended to be **user-facing**: they should read like “what the assistant is doing” rather than raw internal stats.

- `CHAT`: what you would say in a normal chat window.
- `INFO`: clear progress updates and decisions.
- `DETAILED`: deep diagnostics, tool parameters, and (bounded) diffs.

Avoid leaking internal-only identifiers in user-facing logs (caller ids, request ids, opaque tool routing IDs). If you need them, put them in `DETAILED` and keep them minimal.

## Large files, diffs, and "large payloads"

Controllers should encourage assistants to work with slices and bounded output.

Instead of returning huge blobs:

- Use `get_file_slice` or `get_file_with_line_numbers` to fetch only relevant ranges.
- Use `terminal_command` for small, focused commands (`grep`, `sed -n 'start,endp'`, formatters, tests) and bound output (`head`, `tail`, `-n`, explicit ranges).

Write tools print a unified diff (bounded) at `DETAILED` level to make changes visible in Render logs.

## Branches, workspaces, and PRs (controller summary)

Default workflow:

- Do not work directly on the default branch for feature work.
- Use `ensure_branch` / `create_branch` to create a feature branch.
- Use `ensure_workspace_clone` to create or refresh a persistent workspace for the repo+branch.
- Use `terminal_command` in that workspace for tests, linters, and small inspection commands.
- Use `commit_workspace` / `commit_workspace_files` to push changes back to the branch.
- Before opening a PR, run tests/linters (`run_quality_suite`, `run_lint_suite`) and fix failures.

Controller-repo override:

- If explicitly instructed, the assistant may run in **main-branch mode** for this repo (the engine itself).
  In that mode, treat every push as a production deploy: keep changes small, run quality gates, then confirm CI + redeploy before declaring success.

For detailed behavior and examples, see `docs/assistant/ASSISTANT_HANDOFF.md` and `docs/assistant/CONTROLLER_PROMPT_V1.md`.
