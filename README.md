# Adaptiv MCP (GitHub workspace MCP server)

## Workflow: repo mirror vs GitHub live state

This server maintains a persistent server-side git copy for workspace-backed tools.
In this documentation, we call that copy the **repo mirror** to avoid confusion with the tool name `ensure_workspace_clone`.
The repo mirror is the place to edit, run commands, commit, and push.

The repo mirror is not automatically the live GitHub state. GitHub becomes the source of truth after you push.
If you need the repo mirror to exactly match a remote branch after merges/force-updates, you can reset the workspace by rebuilding it.
`ensure_workspace_clone` with `"reset": true` recreates the repo mirror before continuing work.

Tool robustness notes:

- Workspace file tools validate that requested paths resolve inside the repo root and require non-empty path inputs.
- `delete_workspace_paths` requires a non-empty `paths` list; non-empty directory deletion requires `allow_recursive=true`.
- Render tools validate identifiers, clamp pagination limits, enforce `commit_id` XOR `image_url` for deploy creation, and require ISO8601 timestamps for log queries.

Adaptiv is designed to act as an AI model's personal PC, assisting users through the
connected Adaptiv connector with multiple tasks and queries. Today it ships with
GitHub and Render integrations, with plans for additional service integrations in
future updates.

Render integration includes a minimal set of user-facing tools for service
inspection and operations (list owners/workspaces, list services, view deploys,
trigger deploys, rollbacks, restarts, and fetch logs). These tools use Render's
public API and require a Render API token to be configured.

## Quickstart

Production deployment for Adaptiv MCP targets Render.com. The steps below are for local development.

1. Export a GitHub token so the server can authenticate:

   ```bash
   export GITHUB_TOKEN="YOUR_GITHUB_TOKEN"
   ```

2. Run the server locally:

   ```bash
   uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
   ```

3. MCP clients connect to `/sse`, and `/healthz` reports service health.

## Render build and start commands (native Python)

Some Render Python environments restrict installing OS packages during build. This repo vendors a prebuilt `rg` (ripgrep) binary and provides helper scripts.

Build Command:

- `./scripts/render-build.sh`

Start Command:

- `./scripts/render-start.sh`

The start script prepends the vendored `rg` directory to `PATH` and validates `rg --version` before launching Uvicorn.

## Deployment (Render.com)

Adaptiv MCP is deployed via Render.com as a web service for production. Ad-hoc self-hosting is not part of the supported production path; production deployments use Render with environment variables set in the service settings.

Operational notes:

- Render injects `PORT` automatically for web services; the server binds to `$PORT`.
- Configure a GitHub authentication token in Render (for example `GITHUB_TOKEN`), along with any optional variables documented in `docs/usage.md` and `.env.example`.
- (Optional) Set `ALLOWED_HOSTS` to restrict which hostnames may access the MCP transport. If unset and no Render external hostname variables are present, host checks are disabled.
- `/healthz` reports service health and token detection/config defaults.

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
- `/v1/actions` and `/actions` – Actions-compatible tool listing (legacy compatibility surface).
- `/ui` and `/ui.json` – lightweight UI diagnostics (serves `assets/index.html` when present).
- `/static/*` – static assets when the `assets/` directory is present.

## Documentation

- [Usage guide](docs/usage.md) — current functionality, behavior, configuration, and usage patterns.
- [Detailed tools reference](Detailed_Tools.md) — generated tool catalog. If you change the tool surface or schemas, regenerate it with `python scripts/generate_detailed_tools.py`. CI enforces that the generated file is up to date.
