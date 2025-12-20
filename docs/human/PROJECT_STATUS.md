# Project status (engine)

This document is a high-level snapshot of the Adaptiv Controller GitHub MCP server as implemented in this repository.

## What this repo is

- A self-hosted MCP server that exposes a GitHub- and workspace-oriented tool surface.
- Designed to run on Render, but can be self-hosted anywhere that can run a long-lived Python service.
- Intended user experience: assistants feel like “coworkers” because logs read like chat and tools behave like a real engineering environment.

## Current capability summary

### Engineering loop

- Persistent workspace clones per repo/ref.
- Local execution in the workspace via `terminal_command`.
- First-class quality gates: `run_tests`, `run_lint_suite`, `run_quality_suite`.
- Git push flows via `commit_workspace` / `commit_workspace_files`.

### User-facing logs

- Log levels include `CHAT` and `DETAILED`.
- Write tools print a bounded, colored unified diff at `DETAILED` level.
- Intended: `CHAT`/`INFO` answer “what/why/next” like a normal chat assistant.

### Session logs

- Repo-local, durable logs in `session_logs/`.
- Workspace commit helpers append structured entries after successful commits.

### Render integration

- `list_render_logs` + `get_render_metrics` for observability.

### Web browser

- `web_search` and `web_fetch` allow assistants to reference external docs.

## How we ship

- Default is branch-first + PR.
- The controller engine repo may intentionally ship directly to `main` when explicitly instructed.
  - In that mode, every push is treated as a production deploy and must pass local quality gates and GitHub Actions before the service will redeploy.

## Operator notes

- Render redeploy starts only after GitHub Actions is green.
- After redeploy, it can take several minutes to fully start.
- Poll `list_render_logs` every ~60s to confirm the new revision is running.

