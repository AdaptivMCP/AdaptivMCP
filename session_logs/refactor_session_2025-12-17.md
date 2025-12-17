# Refactor session log — 2025-12-17

## Context
Stabilization after the recent refactor.

## Problems observed
- `terminal_command` output occasionally renders with stray/random characters in connector UIs.
- Non-mutating calls can wipe a dirty workspace, forcing `mutating=true` too often.
- Logs on Render/connector UIs can be hard to read when ANSI sequences are emitted.

## Changes
- Strip ANSI escape sequences + control chars from command output.
- If a workspace is dirty, skip destructive refresh (reset/clean) even for non-mutating calls; fetch only.
- Default `LOG_STYLE` to `plain` (no ANSI) unless explicitly enabled.

## 2025-12-17 — Logging + Render CLI improvements

### Summary
- Made CHAT-level tool logs read more like an assistant (first-person, action-oriented) while keeping DETAILED logs technical.
- Added a Render CLI runner tool (`render_cli_command`) and installed the `render` binary in the Docker image.
- Uvicorn access logs (GET/POST lines) are enabled by default; can be disabled via `UVICORN_ACCESS_LOG=0` if you want a quieter Render log view.
- Extended workspace commit tools to append a session log entry after push and commit it back to the repo.

### Verification
- Lint + tests passed locally.

### Next steps
- Render CLI commands require `RENDER_API_KEY` (and service id) in env; configured on the Render service.

## 2025-12-17 — Render CLI workspace auto-select

### Summary
- Render CLI tool now auto-selects a workspace before running commands.
- Set `RENDER_WORKSPACE_ID` (or `RENDER_WORKSPACE_NAME`) in the Render service env so the CLI can run without manual `render workspace set`.
- Workspace selection is persisted via `RENDER_CLI_CONFIG_PATH` (defaults to `/tmp/render-cli/cli.yaml`).

### Verification
- Lint + tests passed locally.

## 2025-12-17 — Render workspace auto-detection on Render

### Summary
- Render CLI workspace selection now falls back to `RENDER_OWNER_ID` (provided by Render at runtime).
- This makes `render_cli_command` usable out-of-the-box on Render without adding `RENDER_WORKSPACE_ID`.

### Verification
- Lint + tests passed.

