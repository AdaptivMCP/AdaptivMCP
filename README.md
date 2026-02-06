# Adaptiv MCP (GitHub + Render)

Adaptiv MCP is a self-hosted, connector-oriented **Model Context Protocol (MCP)** server that exposes **GitHub** and **Render** automation as MCP tools, plus a small HTTP registry/UI surface for discovery and debugging.

It’s designed to work cleanly with **ChatGPT / OpenAI MCP connectors** (including common preflight/probe behavior), while still supporting legacy MCP transports.

- MCP reference: https://modelcontextprotocol.io/

## What you get

### Tooling

- **GitHub automation**
  - repos, branches, files
  - issues + comments
  - pull requests (open/merge/close/comment)
  - GitHub Actions workflows (list runs, trigger dispatch, fetch logs)
- **Render automation**
  - list services / deploys
  - trigger/cancel/rollback deploys
  - restart services
  - fetch logs
- **Workspace / repo mirror** (server-side git working copy)
  - apply file edits safely
  - run commands/tests in a real checkout
  - commit/push and open PRs via a “mirror-first” workflow

### Connector-friendly server behaviors

- **Two MCP transports**
  - **Streamable HTTP (preferred):** `POST /mcp`
  - **Legacy SSE transport:** `GET /sse` + `POST /messages`
- **Preflight-safe endpoints** for `OPTIONS` / `HEAD` / `GET` probes
- **Base-path safe links** via `GET /ui.json` when deployed behind a reverse proxy prefix

See [`docs/chatgpt.md`](docs/chatgpt.md) for practical connector notes.

## Endpoints

MCP transports:

- **Streamable HTTP:** `POST /mcp`
- **SSE:** `GET /sse` and `POST /messages`

HTTP registry/diagnostics:

- `GET /healthz` – runtime health
- `GET /tools` – tool discovery used by connectors
- `POST /tools/<tool_name>` – invoke a tool over HTTP
- `GET /resources` – resource discovery
- `GET /ui` – lightweight UI (links + diagnostics)
- `GET /ui/tools` – tool catalog UI
- `GET /ui.json` – machine-readable service metadata (base-path aware)

## Deploying on Render.com

1) Make a Render.com account and start a Web Service.

<img width="1896" height="711" alt="{FE34540B-8AE0-41A0-97B3-D91FABA184B9}" src="https://github.com/user-attachments/assets/623f34a6-8aa7-4799-8fb8-f59c223db44f" />

2) Use these Start/Build Commands

<img width="1415" height="389" alt="{B62E07CF-D6AB-413F-8181-D5484E7FC75C}" src="https://github.com/user-attachments/assets/570d7dae-b4f3-4e8e-86eb-ddbd0805a71c" />

3) Setup Evironment Variables
Example:
<img width="1678" height="481" alt="{E012574C-E7BA-4AC5-BFA6-2BD653EBACEC}" src="https://github.com/user-attachments/assets/ece377be-f91f-410b-8db7-9e7d7cae3d43" />

(ADAPTIV_MCP_CONTROLLER_REPO set to your mainly worked on Repo. can still see all repos scoped in the Github PAT.)

<img width="1569" height="223" alt="{B25AF1F7-6B36-4E12-BAA0-22BB501F67B9}" src="https://github.com/user-attachments/assets/4e8aaf36-2783-470d-afae-f4a3d01c695b" />

<img width="1567" height="348" alt="{63A3218A-C64F-4551-B8E2-9E23ADEFFABE}" src="https://github.com/user-attachments/assets/0906c70d-f50a-4d81-8471-72a2d7a00916" />

4) After Deploy is successful, you will get a URL. Copy that URL for ChatGPT.

5)Open ChatGPT and go to Settings>Apps>Create App and set it up with the URL you recieved with /sse at the end.

<img width="447" height="704" alt="{57BA9AF6-612A-4423-82DB-75DBEDBBC3E5}" src="https://github.com/user-attachments/assets/1d9f46b4-c2bb-4a11-8155-42cb389af20a" />





## Configuration

The authoritative list of knobs is documented in [`.env.example`](.env.example). Highlights:

### GitHub auth

Set **at least one** token variable:

- `GITHUB_TOKEN` (common)
- `GITHUB_PAT`, `GH_TOKEN`, `GITHUB_OAUTH_TOKEN` (alternates)

Optional:

- `GITHUB_API_BASE` – override for GitHub Enterprise / custom API base (defaults to `https://api.github.com`)

### Render auth

Set one token variable:

- `RENDER_API_KEY` (common)
- `RENDER_API_TOKEN`, `RENDER_TOKEN` (alternates)

Optional:

- `RENDER_API_BASE` – override (defaults to `https://api.render.com`)

### Workspace / repo mirror

Workspace tools operate on a **persistent** server-side repo mirror (git working copy). Useful settings:

- `MCP_WORKSPACE_BASE_DIR` – where mirrors are stored (defaults under your cache directory)
- `MCP_WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS` – safety timeout for patch application

### Write gating (important)

This server distinguishes **read** vs **write** tools and can require explicit approval for write actions.

- `ADAPTIV_MCP_AUTO_APPROVE=true|false` – when enabled, write-capable tools are allowed without an external approval step.

If you’re deploying this in a shared environment, keep auto-approve off unless you understand the implications.

### Logging and timeouts

See `.env.example` for:

- log verbosity + payload truncation controls
- HTTP client timeouts and connection pool limits
- tool execution timeouts
- git author/committer identity used by workspace commits

## Using with ChatGPT / OpenAI MCP connectors

Most OpenAI / ChatGPT MCP connector flows expect the **Streamable HTTP** endpoint.

- **Connector URL / server_url:** `https://<your-host>/mcp`

If you have an older MCP client wired to SSE, it can continue to use:

- `https://<your-host>/sse` (plus `POST https://<your-host>/messages`)

Connector diagnostics:

- `GET /ui.json` – confirms what endpoints the server believes it is serving (including reverse-proxy base paths)
- `GET /tools` – confirms tool discovery
- `GET /healthz` – confirms deployment health

More details: [`docs/chatgpt.md`](docs/chatgpt.md).

## Deployment notes

### Render

This repo includes Render-friendly scripts:

- `scripts/render-build.sh` – installs dependencies with a hash marker to speed subsequent deploys
- `scripts/render-start.sh` – validates a vendored `rg` binary, normalizes log level for uvicorn, and starts the server

The start script expects a working `rg` on `$PATH` and will prefer the vendored binaries under `vendor/rg/...`.

### Reverse proxies / base paths

If you deploy behind a reverse proxy that adds a URL prefix (e.g. `https://host/prefix/...`), use `GET /ui.json` to confirm the derived, prefix-aware endpoints.

## Security & operational notes

- **Principle of least privilege:** use a narrowly scoped GitHub token and Render API key.
- **Write tool approvals:** keep `ADAPTIV_MCP_AUTO_APPROVE=false` in shared environments and wire an external approval workflow if needed.
- **Secrets hygiene:** avoid logging sensitive headers or payloads; prefer short log retention in production.

## Development

```bash
pip install -r dev-requirements.txt

pytest -q
ruff check .
ruff format .
```

## Troubleshooting

- **404 on `/mcp`**: confirm your proxy routes `/mcp` to the service.
- **405 on transport endpoints**: some load balancers probe with `OPTIONS`/`HEAD`; the server includes fallbacks to reduce noisy failures.
- **CORS / browser clients**: key transport endpoints handle permissive `OPTIONS`.
- **Write tools not available / blocked**: check write gating configuration (see `ADAPTIV_MCP_AUTO_APPROVE`).

## Tool catalog

The fastest way to see what’s enabled on a running instance:

- `GET /ui/tools` (human-friendly)
- `GET /tools` (connector-friendly)
- `GET /resources` (resource discovery)
