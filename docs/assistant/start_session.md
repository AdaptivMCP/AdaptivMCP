# Assistant session protocol (Adaptiv Controller)

## Roles and operating model

- **User** = human speaking in chat.
- **Assistant/Operator** = the AI running tools and executing workflows.
- The user does not run tools. The assistant does.
- If any doc says "you" without labeling the audience, treat it as a doc bug and fix it.

See: `docs/human/TERMS_AND_ROLES.md`.


This document is written for assistants using the Adaptiv Controller GitHub MCP server.

The human does not run commands. The assistant does.

## 1) Pre-flight (always)

1. `get_server_config`
   - Confirm write policy.
   - Confirm controller repo + default branch.

2. `validate_environment`
   - Confirm tokens, controller revision metadata, and basic host assumptions.

3. `list_all_actions(include_parameters=true)`
   - Cache tool names and which tools are write-tagged.

4. For any tool you will use (especially write tools):
   - `describe_tool(..., include_parameters=true)`
   - `validate_tool_args(...)`

If you will interact with Render:

- Confirm Render tools exist (`list_all_actions`).
- Confirm required Render env vars are set (`validate_environment`).

## 2) Logging contract (treat logs as the UI)

This product uses stdout (Render logs) as a user-facing UI.

- `CHAT`: speak like you would in a normal chat session.
- `INFO`: short progress and decisions.
- `DETAILED`: tool arguments, diagnostics, and bounded diffs.

Do **not** fill `INFO`/`CHAT` logs with raw counters, caller ids, or internal IDs. If something is needed for debugging, keep it minimal and put it in `DETAILED`.

## 3) Branch strategy

Default:

- Create a feature branch and open a PR.
- Never develop directly on the default branch for feature work.

Controller-repo override (live main-branch mode):

- If explicitly instructed, you may commit directly to `main` for this repo.
- Treat pushes as production deploys:
  - Keep changes small.
  - Run `run_quality_suite` and `run_lint_suite`.
  - Confirm GitHub Actions is green.
  - Confirm Render redeploy and validate with `list_render_logs`.

## 4) Workspace workflow (normal engineering loop)

1. `ensure_workspace_clone(full_name=..., ref=..., reset=...)`
   - Use `reset=true` when you suspect the clone is stale or dirty.

2. Inspect and edit using workspace-native commands:
   - Read with `get_file_slice` / `get_file_with_line_numbers`.
   - Edit with an editor/tooling in the workspace via `terminal_command`.

3. Verify locally:
   - `run_tests` (narrow first; then the full suite as needed)
   - `run_lint_suite`
   - `run_quality_suite` (recommended before any push)

4. Commit and push:
   - `commit_workspace` / `commit_workspace_files`
   - Keep commits scoped and descriptive.

5. After push:
   - For controller-repo work on Render, confirm CI green then redeploy completed.
   - Use `list_render_logs(limit=100, direction='backward')` to confirm the new revision is running.

## 5) Session logs

Session logs live inside the repo under `session_logs/`.

- Name sessions like: `session_logs/refactor_session_YYYY-MM-DD.md`.
- Commit/push helpers will append a structured entry after successful workspace commits.
- If you make changes via non-workspace write helpers (Contents API commits), ensure the session log still captures:
  - What changed
  - Why it changed
  - How it was tested
  - What to verify after deploy

## 6) Web browser tools (when needed)

Use these when you need external information:

- `web_search(query=...)`
- `web_fetch(url=...)`

Prefer primary sources (official docs, READMEs, changelogs).

