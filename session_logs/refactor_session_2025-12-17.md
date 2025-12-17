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

