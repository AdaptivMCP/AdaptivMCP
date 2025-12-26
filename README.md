# Adaptiv Controller – MCP Server

This repository is a self-hosted GitHub MCP (Model Context Protocol) server hosted through Render.com Web Service Python Environment.
It exposes a safe, engineering-oriented tool surface so ChatGPT AI Models (Currently tested up to model 5.2 Thinking) can assist users better.

## Health and observability

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, token-present signal, in-memory metrics snapshot).
- `/sse` – MCP transport endpoint.

Metrics are in-memory only (reset on restart) and never include secrets.

## Documentation

- [Usage guide](docs/usage.md) — current functionality, behavior, configuration, and usage patterns.
- [Detailed tools reference](Detailed_Tools.md) — tool catalog grouped by function.
