# Adaptiv MCP (GitHub + Render MCP server)

Adaptiv MCP is an MCP (Model Context Protocol) server that provides GitHub and Render operations to MCP clients.

It supports two complementary ways of working with GitHub repositories:

- GitHub API tools operate directly against GitHub's remote state (REST + GraphQL).
- Workspace tools operate on a persistent server-side git working copy (the "repo mirror").

The code is the authoritative reference. Documentation is expected to track runtime behavior.

## Repo mirror vs live GitHub state

The server maintains a persistent server-side git working copy for workspace-backed tools. In this documentation we call that copy the **repo mirror** (created/reused via `ensure_workspace_clone`).

The repo mirror is not automatically the live GitHub state. The remote branch reflects updates only after you push.
If you need the repo mirror to exactly match a remote branch after merges/force-updates, rebuild it with `ensure_workspace_clone(reset=true)`.

For a glossary of terms used across docs and code, see `docs/terminology.md`.

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

- Bootstrap a local venv: `make bootstrap` (or `python scripts/bootstrap.py`)
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

- [Usage guide](docs/usage.md) — tool surface, configuration, operational behavior.
- [Terminology and glossary](docs/terminology.md) — stable definitions used across docs and code.
- [Architecture and safety](docs/architecture_safety.md) — safety posture and guardrails.
- [Tool robustness](docs/tool_robustness.md) — validation rules and common patterns.
- [Detailed tools reference](Detailed_Tools.md) — generated tool catalog grouped by function.
