# Adaptiv Controller – MCP Server

This repository is a self-hosted GitHub MCP (Model Context Protocol) server.
It exposes a safe, engineering-oriented tool surface so an assistant (for example a ChatGPT custom GPT) can work on GitHub repos using normal software practices: branches, diffs, tests/linters, and pull requests.

## Health and observability

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, token-present signal, in-memory metrics snapshot).
- `/sse` – MCP transport endpoint.

Metrics are in-memory only (reset on restart) and never include secrets.

