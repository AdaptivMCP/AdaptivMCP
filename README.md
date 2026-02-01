# Adaptiv MCP (GitHub + Render)

Adaptiv MCP is a connector-oriented **Model Context Protocol (MCP)** server that exposes **GitHub** and **Render** automation as MCP tools, plus a small HTTP registry/UI surface for discovery and debugging.

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

## Quickstart (local)

### 1) Install

```bash
python -m venv .venv
source .venv/bin/activate

# Runtime deps only (recommended for running the server)
pip install -r requirements.txt

# OR: dev deps (includes runtime + tests/lint + python-dotenv)
# pip install -r dev-requirements.txt
```

### 2) Configure env vars

Copy the sample env file and set at least a GitHub token:

```bash
cp .env.example .env
# edit .env
```

Notes:

- If `python-dotenv` is installed, the server will load values from `.env` automatically (see `.env.example` comments).
- You usually only need **one** of the supported GitHub token variables (commonly `GITHUB_TOKEN`).
- Render tools require a Render API token (`RENDER_API_KEY` or one of its aliases).

### 3) Run

```bash
uvicorn main:app --reload --port 8000
```

Open:

- `http://localhost:8000/ui`
- `http://localhost:8000/ui.json`

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

---

### Compatibility note

This server keeps **both** MCP transports available:

- Some clients still reference `/sse`.
- Newer OpenAI connector flows reference `/mcp`.

If you deploy behind a reverse proxy that adds a base path prefix, `/ui.json` will report the correct prefixed endpoints.
