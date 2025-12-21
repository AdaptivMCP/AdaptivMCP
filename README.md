# Adaptiv Controller – MCP Server

This repository is a self-hosted GitHub MCP (Model Context Protocol) server.
It exposes a safe, engineering-oriented tool surface so an assistant (for example a ChatGPT custom GPT) can work on GitHub repos using normal software practices: branches, diffs, tests/linters, and pull requests.

Operator checklist for any report of “tools are missing” or “it’s acting weird” (tool events include `user_message` for UI-friendly logs):

- `get_recent_tool_events(limit=50, include_success=true)`
- `get_server_config`
- `list_all_actions(include_parameters=true)`
- `validate_environment`
- `/healthz`

## Health and observability

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, token-present signal, in-memory metrics snapshot).
- `/sse` – MCP transport endpoint.
- `/static` – static assets (connector icons, branding).

Metrics are in-memory only (reset on restart) and never include secrets.

