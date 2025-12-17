# Assistant handoff

This file is a short onboarding note for assistants using this MCP server.

## Read these first

1. `docs/assistant/start_session.md` (required start-session checklist)
2. `docs/human/WORKFLOWS.md` (how to operate)
3. `docs/human/ARCHITECTURE_AND_SAFETY.md` (safety model)
4. `Detailed_Tools.md` (tool names + intent)

## Operating rules

### Logs are UI

Write logs like you are talking to the user in a ChatGPT chat window.

- `CHAT` / `INFO`: what/why/next.
- `DETAILED`: diffs, command output, deep context.

Do not leak internal IDs, raw tool payloads, or anything token-like.

### Branch strategy

Default (most repos):

- branch-first + PR.

Controller engine repo (this repo) may be operated in **direct-to-main** mode *only when explicitly instructed*. In that mode:

- treat every push as production shipping.
- run local quality gates.
- ensure GitHub Actions is green.
- verify the provider redeploy (Render logs).

### Quality gates

Before you ship:

- `run_tests`
- `run_lint_suite`
- or `run_quality_suite` (preferred).

### Session logs

When you make meaningful progress (especially when committing/pushing), ensure the repo-local `session_logs/` captures:

- what changed and why,
- what was verified,
- what remains.

If the tooling does not append automatically for a path you used, add a short manual entry.

## Fast recovery checklist

If something feels “off”:

- Verify server config: `get_server_config`, `validate_environment`.
- Verify tools: `list_all_actions`.
- Verify workspace health:
  - `ensure_workspace_clone`, `get_workspace_changes_summary`.
- Verify provider:
  - `list_render_logs`, `get_render_metrics`.
- Inspect server memory logs:
  - `get_recent_server_errors`, `get_recent_server_logs`, `get_recent_tool_events`.
