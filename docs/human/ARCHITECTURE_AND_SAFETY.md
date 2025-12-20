# Architecture and safety model

This document explains how the Adaptiv Controller GitHub MCP server is structured and what safety guarantees it tries to enforce.

It is written for:

- Operators deploying the server (Render/Docker).
- Developers modifying the engine.
- Assistants/controllers that must behave predictably and safely.

## What this service is

- An **MCP server** exposing a tool surface for:
  - GitHub reads/writes (repos, files, issues, PRs, Actions).
  - A persistent **workspace clone** used for local execution (`terminal_command`) and quality gates.
  - Provider integrations (Render logs/metrics/CLI).
  - Limited web browsing (search + fetch).

The goal is a “coworker” experience: assistants do real work and narrate progress in **user-facing logs**.

---

## High-level layout

### Entrypoints

- `main.py`
  - Creates the FastMCP/Starlette app.
  - Registers the core tool surface.
  - Wires the write gate, logging, and environment validation.

- `extra_tools.py`
  - Optional tools that can be enabled/loaded without changing the core entry surface.

### Core packages

- `github_mcp/mcp_server/`
  - Tool registry, schema helpers, error rendering, context, and the write gate.

- `github_mcp/main_tools/`
  - GitHub-oriented tool implementations.

- `github_mcp/workspace_tools/`
  - Workspace-backed tools (clone management, command execution, commit/push, suites).

- `github_mcp/http_routes/`
  - Minimal HTTP endpoints (`/healthz`) and compatibility endpoints.

- `github_mcp/session_logs.py`
  - Helpers to write durable, repo-local session logs under `session_logs/`.

---

## Request flow

1. ChatGPT invokes an MCP tool with JSON arguments.
2. The server validates inputs (schema + basic safety checks).
3. The tool runs under an execution context that captures:
   - User-facing log lines.
   - Recent tool events.
   - Recent server errors.
4. The tool returns a structured JSON response (and often includes a concise summary).

The **canonical tool list and schemas** can be inspected at runtime with:

- `list_all_actions`
- `describe_tool`

---

## Safety model

### 1) Write gate

Tools that modify state are write-gated.

- Default behavior starts with write actions blocked until explicitly authorized.
  - When false/unset: write tools require an explicit `authorize_write_actions(approved=True)`.
  - When true: write tools are allowed by default, but can be disabled per session.

Write-gating is enforced in the server layer (not “by convention”).

### 2) Default branch and target refs

The server treats the controller repo’s default branch (`GITHUB_MCP_CONTROLLER_BRANCH`, default `main`) as canonical.

Recommended operating model:

- For most repos: branch-first + PR.
- For this controller repo (when explicitly instructed): direct-to-`main` is allowed, but treated as **production shipping**.

### 3) Workspace containment

Workspace tools operate in a persistent clone directory (see `.env.example` for workspace base dir settings).

- `terminal_command` runs commands inside the workspace directory.
- File reads/writes have bounded output to protect the client.
- Workspace listing/search tools are bounded (no unbounded directory dumps).

### 4) Output truncation

To reduce “conversation drops” caused by oversized tool outputs:

- Stdout/stderr are clamped (configurable via `TOOL_STDOUT_MAX_CHARS`, `TOOL_STDERR_MAX_CHARS`, `TOOL_STDIO_COMBINED_MAX_CHARS`).
- Tools return truncation flags so assistants can react (rerun with narrower output, fetch specific logs, etc.).

### 5) Web browsing constraints

Internet access is intentionally constrained:

- `web_search` returns titles/snippets.
- `web_fetch` retrieves a single URL with conservative checks.

If you need a broader browser, add it deliberately and keep it safety-reviewed.

---

## Logging contract

Logs are part of the product.

- `CHAT` / `INFO` log lines should read like a ChatGPT response:
  - What is happening.
  - Why it is happening.
  - What will happen next.
- `DETAILED` may include:
  - Diffs (colored when supported).
  - Command output.
  - Deep diagnostic context.

Avoid dumping:

- Internal IDs (caller IDs, internal correlation IDs) unless debugging.
- Raw JSON payloads that are not human-friendly.
- Tokens/secrets.

The goal is that a user can reconstruct the assistant’s plan and progress from logs alone.

---

## Where to look when debugging

- Tool surface and schemas:
  - `list_all_actions`, `describe_tool`

- Live environment checks:
  - `validate_environment`, `get_server_config`

- Recent internal state:
  - `get_recent_tool_events`, `get_recent_server_logs`, `get_recent_server_errors`

- Render provider:
  - `list_render_logs`, `get_render_metrics`

- Workspace:
  - `ensure_workspace_clone`, `get_workspace_changes_summary`, `run_quality_suite`
