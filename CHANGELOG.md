# Changelog

All notable changes to this repository are documented here.

The changelog is intentionally **operator-facing**:

- What changed in the engine.
- What behavior changed for assistants/controllers.
- What operators must update (env vars, CI, deployment).

## Unreleased

### Added

- Render observability tools:
  - `list_render_logs`, `get_render_metrics`.
- Render CLI tool:
  - `render_cli_command` (non-interactive wrapper).
- Web browser tools:
  - `web_search`, `web_fetch`.
- Repo-local session logs:
  - `session_logs/` directory + helpers that append durable commit/session notes.
- User-facing progress logs:
  - `get_recent_tool_events`, `get_recent_server_logs`, `get_recent_server_errors`.
- Workspace quality gates:
  - `run_tests`, `run_lint_suite`, `run_quality_suite`.

### Changed

- Documentation refresh:
  - Canonical workflow docs moved under `docs/human/`.
  - Assistant playbooks refreshed under `docs/assistant/`.
- Tool naming guidance:
  - `terminal_command` is the primary workspace command runner.

### Deprecated

- `run_command` remains as a compatibility alias for `terminal_command`.
- `fetch_url` remains as a compatibility wrapper; prefer `web_fetch` for internet access.

## 1.0.0

- Initial 1.0 release of the Adaptiv Controller GitHub MCP server.
