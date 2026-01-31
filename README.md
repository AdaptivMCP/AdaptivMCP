# Adaptiv MCP (GitHub + Render)

A connector-oriented [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that exposes:

- **GitHub automation** (issues, PRs, repos, workflows)
- **Render automation** (services, deploys, logs)
- **HTTP tool registry** for LLM / connector-style invocation

This repo is designed to work well with **ChatGPT / OpenAI MCP connectors** out of the box.

## Endpoints

The server exposes both MCP transports:

- **Streamable HTTP (preferred for ChatGPT/OpenAI connectors):** `POST /mcp`
- **SSE transport (backwards-compatible):** `GET /sse` + `POST /messages`

And HTTP registry/diagnostics:

- `GET /healthz` – deploy + runtime health
- `GET /tools` – tool discovery
- `POST /tools/<tool_name>` – invoke a tool
- `GET /resources` – resource discovery
- `GET /ui` – lightweight UI (links + diagnostics)
- `GET /ui/tools` – tool catalog UI
- `GET /ui.json` – machine-readable service metadata

## Quickstart (local)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

uvicorn main:app --reload --port 8000
```

Then open:

- `http://localhost:8000/ui`
- `http://localhost:8000/ui.json`

## Using with ChatGPT / OpenAI MCP connectors

Most OpenAI / ChatGPT MCP connector flows expect the Streamable HTTP endpoint.

- **Connector URL / server_url:** `https://<your-host>/mcp`

If you have an existing client wired to SSE, it can continue to use:

- `https://<your-host>/sse` (plus `POST https://<your-host>/messages`)

See [`docs/chatgpt.md`](docs/chatgpt.md) for practical connector setup notes and troubleshooting.

## Configuration

### GitHub

This server is intended to run with a GitHub App installation token or PAT depending on your deployment model.
Search the repo for `GITHUB_` env vars for your deployment target.

### Render

Render endpoints require one of:

- `RENDER_API_KEY`
- `RENDER_API_TOKEN`

## Development

- Run tests: `pytest -q`
- Lint/format: `ruff check .` and `ruff format .`

---

### Notes on compatibility

This server intentionally keeps **both** transports available:

- Some clients and older documentation still reference `/sse`.
- Newer OpenAI connector docs reference `/mcp`.

If you deploy behind a reverse proxy that adds a base path prefix, `/ui.json` will report the correct prefixed endpoints.
