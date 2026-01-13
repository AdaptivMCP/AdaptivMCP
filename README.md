# Adaptiv MCP (GitHub workspace MCP server)

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

Render integration includes a minimal set of user-facing tools for service
inspection and operations (list owners/workspaces, list services, view deploys,
trigger deploys, rollbacks, restarts, and fetch logs). These tools use Render's
public API and require a Render API token to be configured.

## Quickstart

Production deployment for Adaptiv MCP is **Render.com only**. The steps below are for local development.

1. Export a GitHub token so the server can authenticate:

   ```bash
   export GITHUB_TOKEN="YOUR_GITHUB_TOKEN"
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

Vendored ripgrep (rg):

- Start a shell with `rg` on PATH: `make rg-shell` (or `./scripts/dev-shell.sh`)
- Or, in an existing shell: `. ./scripts/rg-path.sh`

- Install dev dependencies: `make install-dev`
- Lint: `make lint`
- Format: `make format`
- Test: `make test`
- (Optional) Install + run pre-commit: `make precommit`

See `CONTRIBUTING.md` for additional details.

## HTTP endpoints

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, token-present signal).
- `/sse` – MCP transport endpoint (SSE).
- `/messages` – MCP message submit endpoint used by the SSE transport.
- `/tools` – tool registry for discovery (supports `?include_parameters=` and `?compact=`).
- `/resources` – compatibility resource listing for MCP clients.
- `/tools/<name>` – tool detail (GET) and invoke (POST).
- `/ui` and `/ui.json` – lightweight UI diagnostics (serves `assets/index.html` when present).
- `/static/*` – static assets when the `assets/` directory is present.

## Documentation

- [Usage guide](docs/usage.md) — current functionality, behavior, configuration, and usage patterns.
- [Detailed tools reference](Detailed_Tools.md) — tool catalog grouped by function.
