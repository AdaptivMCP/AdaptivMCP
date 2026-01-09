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

## Quickstart

Production deployment for Adaptiv MCP is **Render.com only**. The steps below are for local development.

1. Export a GitHub token so the server can authenticate:

   ```bash
   export GITHUB_TOKEN="ghp_your_token_here"
   ```

2. Run the server locally:

   ```bash
   uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
   ```

3. Point your MCP client to `/sse` and verify `/healthz` is healthy.

## Render build and start commands (native Python)

Some Render Python environments do not allow installing OS packages during build. This repo vendors a prebuilt `rg` (ripgrep) binary and provides helper scripts.

Build Command:

- `./scripts/render-build.sh`

Start Command:

- `./scripts/render-start.sh`

The start script prepends the vendored `rg` directory to `PATH` and validates `rg --version` before launching Uvicorn.

## Deployment (Render.com only)

Adaptiv MCP is deployed exclusively via Render.com as a web service. For production, do not run this server via ad-hoc self-hosting. Instead, deploy through Render and configure environment variables in the Render service settings.

Operational notes:

- Render injects `PORT` automatically for web services; the server should bind to `$PORT`.
- Configure a GitHub authentication token in Render (for example `GITHUB_TOKEN`), along with any optional variables documented in `docs/usage.md` and `.env.example`.
- Use `/healthz` to validate that the service is healthy and that token detection/config defaults are as expected.

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

## Health

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, token-present signal).
- `/sse` – MCP transport endpoint.

## Documentation

- [Usage guide](docs/usage.md) — current functionality, behavior, configuration, and usage patterns.
- [Detailed tools reference](Detailed_Tools.md) — tool catalog grouped by function.
