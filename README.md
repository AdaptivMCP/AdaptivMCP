# Adaptiv MCP Server (GitHub + Workspace Mirror)

This repository ships a self-hosted **Model Context Protocol (MCP)** server that exposes a GitHub automation surface (read/write) and an optional **server-side workspace mirror** (persistent git clone) for workflows that require filesystem access, command execution, or test runs.

The server is commonly deployed on **Render.com**, and then connected to a controller client (for example, ChatGPT) via MCP (SSE / stdio) and/or a lightweight HTTP tool registry.

## What you get

- **GitHub API tools**: repository inspection, file CRUD, issues/PRs, Actions workflows, search, GraphQL, etc.
- **Workspace mirror tools**: persistent per-repo/per-branch clones, safe file edits, ripgrep search, git porcelain, running tests/lint, and PR creation from the workspace.
- **Workflows**: higher-level end-to-end helpers (apply edits → run quality → commit/push → open PR).

## Tooling overview

This project exposes *MCP tools* (server-side functions decorated with `@mcp_tool`) and can be invoked by a variety of clients.

- **MCP client mode**: a client speaks MCP directly to this server.
- **HTTP tool-registry mode**: a client calls the server’s HTTP tool endpoints (a convenience transport).
- **“API tool” wrappers**: some clients (including ChatGPT tool integrations) call the server via a wrapper API; the underlying operation is still an MCP tool.

For a clear definition of *API tool vs MCP tool vs both* and common workflows, see **docs/TOOLING.md**.

## Repository layout

- `github_mcp/main_tools/` — API-backed MCP tools (GitHub, Render, Actions, etc.)
- `github_mcp/workspace_tools/` — workspace mirror tools (filesystem + git + command execution)
- `github_mcp/tools_main.py` — stable import to eagerly register all `main_tools`
- `github_mcp/tools_workspace.py` — stable import to eagerly register all `workspace_tools`

## Development

Typical local development loop:

1. Configure environment (GitHub auth, optional Render auth).
2. Run the server.
3. Connect your MCP client and list tools.

Note: deployment-specific configuration (Render service config, secrets, base URLs) varies by environment.

## Documentation

- **Tool definitions, operations, and workflows**: `docs/TOOLING.md`
