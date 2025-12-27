# Adaptiv Controller – MCP Server

Adaptiv is designed to act as an AI model's personal PC, assisting users through the
connected Adaptiv connector with multiple tasks and queries. Today it ships with
GitHub and Render integrations, with plans for additional service integrations in
future updates.

## Health and observability

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, token-present signal, in-memory metrics snapshot).
- `/sse` – MCP transport endpoint.

Metrics are in-memory only (reset on restart) and never include secrets.

## Documentation

- [Usage guide](docs/usage.md) — current functionality, behavior, configuration, and usage patterns.
- [Detailed tools reference](Detailed_Tools.md) — tool catalog grouped by function.
