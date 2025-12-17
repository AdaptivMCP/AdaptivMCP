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

