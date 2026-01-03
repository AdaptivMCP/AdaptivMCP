# Adaptiv Controller – MCP Server

## Workflow: clone vs GitHub live state

This server maintains a persistent server-side git clone for workspace-backed tools.
That clone is the place to edit, run commands, commit, and push.

The clone is not automatically the live GitHub state. GitHub becomes the source of truth only after you push.
If you need the local clone to exactly match a remote branch after merges/force-updates, you can reset the workspace by re-cloning.
Use `ensure_workspace_clone` with `"reset": true` to recreate the workspace clone before continuing work.

Adaptiv is designed to act as an AI model's personal PC, assisting users through the
connected Adaptiv connector with multiple tasks and queries. Today it ships with
GitHub and Render integrations, with plans for additional service integrations in
future updates.

## Development

- Install dev dependencies: `make install-dev`
- Lint: `make lint`
- Format: `make format`
- Test: `make test`
- (Optional) Install + run pre-commit: `make precommit`

See `CONTRIBUTING.md` for additional details.

## Tool registry defaults

By default, this server does not disable any MCP tools (the built-in denylist is empty). Operators can optionally disable specific tools at deployment time by setting `MCP_TOOL_DENYLIST` to a comma-separated list of tool names.

Setting `MCP_TOOL_DENYLIST` to `none` (also accepts `off`, `false`, or `0`) explicitly disables the denylist.

Note: Client/platform-level safety gating (if any) is independent of this server’s tool registry behavior.

## Health and observability

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, token-present signal, in-memory metrics snapshot).
- `/sse` – MCP transport endpoint.

Metrics are in-memory only (reset on restart) and never include secrets.

## Documentation

- [Usage guide](docs/usage.md) — current functionality, behavior, configuration, and usage patterns.
- [Detailed tools reference](Detailed_Tools.md) — tool catalog grouped by function.
