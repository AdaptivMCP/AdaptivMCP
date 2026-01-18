# Adaptiv MCP (GitHub + Render MCP server)

Adaptiv MCP is an MCP (Model Context Protocol) server that provides GitHub and Render operations to MCP clients.

It supports two complementary ways of working with GitHub repositories:

- GitHub API tools operate directly against GitHub's remote state (REST + GraphQL).
- Workspace tools operate on a persistent server-side git working copy (the "repo mirror").

The code is the authoritative reference. Documentation is expected to track runtime behavior.

## Repo mirror vs live GitHub state

The server maintains a persistent server-side git working copy for workspace-backed tools. In this documentation we call that copy the **repo mirror** (created/reused via `ensure_workspace_clone`).

The repo mirror is not automatically the live GitHub state. The remote branch reflects updates only after changes are pushed.

`ensure_workspace_clone(reset=true)` rebuilds the repo mirror from the selected remote ref. This operation is relevant after merges or force-updates on the remote branch, or when a fully clean working tree is required.

For a glossary of terms used across docs and code, see `docs/terminology.md`.

## Local execution profile

Production deployment targets Render.com. Local execution mirrors the same HTTP surface and environment-variable driven configuration.

Common environment variables:

```bash
export GITHUB_TOKEN="..."  # GitHub authentication for API-backed tools
export PORT=8000           # Optional; defaults to 8000 for local runs
```

Example local server invocation:

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

MCP clients connect via `/sse`. `/healthz` returns a compact health payload.

## Render build and start commands

Some Render Python environments restrict installing OS packages during build. This repo vendors a prebuilt `rg` (ripgrep) binary and provides helper scripts.

Build command:

- `./scripts/render-build.sh`

Start command:

- `./scripts/render-start.sh`

The start script prepends the vendored `rg` directory to `PATH` and validates `rg --version` before launching Uvicorn.

## Deployment (Render.com)

Adaptiv MCP is deployed via Render.com as a web service for production. Ad-hoc self-hosting is not part of the supported production path; production deployments use Render with environment variables set in the service settings.

Operational notes:

- Render injects `PORT` automatically for web services; the server binds to `$PORT`.
- Configure a GitHub authentication token in Render (for example `GITHUB_TOKEN`), along with any optional variables documented in `docs/usage.md` and `.env.example`.
- (Optional) Set `ALLOWED_HOSTS` to restrict which hostnames may access the MCP transport. If unset and no Render external hostname variables are present, host checks are disabled.
- `/healthz` reports service health and token detection/config defaults.

## Development commands

Vendored ripgrep (rg):

- Shell with `rg` on `PATH`: `make rg-shell` (or `./scripts/dev-shell.sh`)
- Add `rg` to `PATH` in an existing shell: `. ./scripts/rg-path.sh`

Common development commands:

- Virtual environment bootstrap: `make bootstrap` (or `python scripts/bootstrap.py`)
- Dev dependencies: `make install-dev`
- Lint: `make lint`
- Format: `make format`
- Test: `make test`
- Pre-commit hooks (optional): `make precommit`

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
