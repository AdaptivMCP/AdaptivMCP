# ChatGPT / OpenAI connector notes

This repository is built to work cleanly with ChatGPT / OpenAI MCP connectors.

## Which MCP endpoint should I use?

Prefer the **Streamable HTTP** MCP endpoint:

- `https://<your-host>/mcp`

This aligns with recent OpenAI connector guidance and avoids the two-endpoint requirement of SSE (`/sse` + `/messages`).

The server still supports the legacy SSE transport for backwards compatibility:

- `https://<your-host>/sse`
- `POST https://<your-host>/messages`

## Common connector behaviors this repo supports

### 1) Preflight / probing requests

Some environments will probe transport endpoints using `OPTIONS`, `GET`, or `HEAD`.

- The server mounts Streamable HTTP at `/mcp` and responds to permissive `OPTIONS`.
- SSE endpoints also have lightweight fallbacks to avoid noisy `405 Method Not Allowed`.

### 2) ChatGPT-specific metadata headers

When the request includes OpenAI/ChatGPT metadata headers, the server records them in request context and formats errors in a connector-friendly shape.

This keeps connector UX consistent even when an internal tool raises a structured error.

### 3) Base-path safe links

If you deploy behind a reverse proxy (e.g. `https://host/prefix/...`), `GET /ui.json` derives and reports the correct prefixed endpoints.

## Troubleshooting

- **404 on `/mcp`**: ensure you deployed a version that mounts Streamable HTTP (this repo does), and that your reverse proxy routes `/mcp` to the service.
- **405 on transport endpoints**: load balancers can send probes; the server includes fallbacks to avoid 405s on common probes.
- **CORS / browser clients**: `OPTIONS` is handled permissively on key transport endpoints.

## Useful diagnostics

- `GET /ui.json` – lists the endpoints the server believes it is serving
- `GET /ui/tools` – browse tools + filter by read/write
- `GET /tools` – tool list used by connectors
- `GET /healthz` – runtime health
