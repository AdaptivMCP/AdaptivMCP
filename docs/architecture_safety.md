# Adaptiv Controller (GitHub MCP) Architecture & Safety Review

This document describes the architecture and safety posture of the Adaptiv Controller GitHub MCP server based on a review of the code modules. It maps core subsystems to their implementation files and calls out security/safety considerations surfaced in the code.

## 1. High-level architecture

The server is an ASGI application that exposes a Model Context Protocol (MCP) tool surface for GitHub operations and local workspace tooling. The implementation combines:

- **Entry-point ASGI app**: `main.py`
- **Core MCP server plumbing**: `github_mcp/mcp_server/*`
- **Tool families**: `github_mcp/main_tools/*` and `github_mcp/workspace_tools/*`
- **GitHub API clients + caching**: `github_mcp/http_clients.py`, `github_mcp/github_content.py`, `github_mcp/file_cache.py`
- **Health endpoint**: `github_mcp/http_routes/healthz.py`

### Execution flow (simplified)

```
Client (ChatGPT / connector)
    │
    ├─> ASGI app (main.py)
    │     ├─ Middleware: request context, cache-control
    │     ├─ HTTP routes: /healthz, /sse, /static
    │     └─ FastMCP server dispatch
    │
    └─> Tool registry (github_mcp/mcp_server/decorators.py)
          ├─ Side-effect classification
          ├─ Best-effort dedupe for retries
          └─ Tool implementation (main_tools/*, workspace_tools/*)
```

## 2. Module-by-module architecture overview

### 2.1 Entry point + ASGI wiring

- **`main.py`**
  - Sets up the FastMCP server as an ASGI app.
  - Implements middleware for:
    - **Cache-control**: no-store for dynamic endpoints; cacheable for static assets.
    - **Request context**: extracts `session_id`, MCP JSON-RPC `id`, and safe ChatGPT metadata headers for dedupe/logging.
  - Registers HTTP routes (health check, actions compat routes).
  - Exposes tool definitions and metadata through imported tool modules.

### 2.2 Core MCP server glue

- **`github_mcp/mcp_server/context.py`**
  - Initializes `FastMCP` instance and shared contextvars for request metadata.
  - Captures safe ChatGPT metadata headers (conversation/assistant/org/project/session/user IDs) for log correlation.
  - Defines the write auto-approval flag (`WRITE_ALLOWED`) sourced from the `GITHUB_MCP_WRITE_ALLOWED` environment variable.
  - Wraps MCP session response to suppress SSE disconnect noise.

- **`github_mcp/mcp_server/decorators.py`**
  - Implements the `@mcp_tool` decorator:
    - Registers tools with FastMCP while keeping Python-callable functions.
    - Adapts registration to FastMCP tool signature variants (with or without tag support).
    - Performs best-effort dedupe to avoid double execution on retries.
  - Calculates side-effect class for each tool.
  - Emits structured tool-call logs with a scan-friendly message plus machine-readable `data=<json>`.

- **`github_mcp/mcp_server/registry.py`, `errors.py`, `schemas.py`**
  - Registry for tool metadata and schema normalization.
  - Structured error responses for tool failures.
  - Metadata sanitation for log payloads.

### 2.3 Tool families

- **`github_mcp/main_tools/*`**
  - Implements GitHub-focused tools (issues, repos, PRs, workflows, branches, files).
  - Provides additional utility tools for diagnostics, normalization, server config introspection, etc.
  - Many tools route GitHub requests through `_github_request` to share HTTP client behavior.

- **`github_mcp/workspace_tools/*`**
  - Implements local workspace operations: file I/O, git commands, branching, commit, and running shell commands.
  - Shares common helpers in `_shared.py` (safe branch naming, workspace diagnostics, git env setup).

- **`github_mcp/tools_workspace.py`**
  - Compatibility layer that exposes workspace operations to the MCP surface.
  - Provides higher-level workspace orchestration (clone, command, file access, commit, etc.).

### 2.4 GitHub API access + caching

- **`github_mcp/http_clients.py`**
  - Builds and manages async HTTP clients for GitHub and external requests.
  - Implements token lookup from environment variables.
  - Enforces per-event-loop concurrency caps and refreshes clients on loop changes.
  - Includes retry/backoff logic for rate limits.

- **`github_mcp/github_content.py`**
  - Fetches and decodes GitHub repository content.
  - Integrates with file cache to avoid repeated fetches.

- **`github_mcp/file_cache.py`**
  - LRU cache for decoded file payloads with size and entry caps.

### 2.5 Workspace execution

- **`github_mcp/workspace.py`**
  - Shell command runner with timeout handling.
  - Git operations with retry on rate limit errors.
  - Injects Git author/committer environment variables for reproducible commits.
  - Builds authentication env for Git using `GIT_HTTP_EXTRAHEADER` and config env.
  - Git identity defaults prefer explicit `GITHUB_MCP_GIT_*` env vars, then legacy `GIT_*`,
    then GitHub App metadata, and finally placeholders (which trigger warnings).

### 2.6 Health

- **`github_mcp/http_routes/healthz.py`**
  - `/healthz` endpoint reporting uptime, token presence, controller defaults, and
    warnings for placeholder git identity.

## 3. Safety & security evaluation

### 3.1 Authentication and secret handling

- GitHub tokens are read from environment variables (`GITHUB_PAT`, `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_OAUTH_TOKEN`).
- Token usage is localized to request helpers; tokens are **not** stored in files.
- Git authentication for `git` commands uses `GIT_HTTP_EXTRAHEADER` and config env injection, keeping secrets out of CLI arguments.

**Relevant modules:**
- `github_mcp/http_clients.py` (`_get_github_token`)
- `github_mcp/workspace.py` (`_git_auth_env`)

### 3.2 Write gating & approvals

- The effective write auto-approval flag is sourced from `GITHUB_MCP_WRITE_ALLOWED` (via `WRITE_ALLOWED`).
- Write tools remain executable when auto-approval is disabled; clients should prompt/confirm before invoking write tools.
- Introspection surfaces three distinct concepts:
  - `write_action`: whether the tool is classified as a write.
  - `write_allowed`: whether the tool is executable (approval-gated writes still execute).
  - `write_auto_approved` / `write_actions_enabled`: whether writes are auto-approved.
  - `approval_required`: whether a client should prompt before invoking the tool.

**Implication:**
- Write safety is *metadata-based* and depends on operator configuration and client behavior.

**Relevant modules:**
- `github_mcp/mcp_server/context.py` (`GITHUB_MCP_WRITE_ALLOWED`, `WRITE_ALLOWED`)
- `github_mcp/main_tools/introspection.py` (introspection fields)

### 3.3 Dedupe and retry behavior

- Tool calls are de-duplicated in-memory to mitigate retry storms.
- GitHub API calls are retried with backoff when rate limits are detected.
- Git operations are retried for rate-limit error messages.

**Relevant modules:**
- `github_mcp/mcp_server/decorators.py` (dedupe)
- `github_mcp/http_clients.py` (API retry/backoff)
- `github_mcp/workspace.py` (`_run_git_with_retry`)

### 3.4 Command execution safeguards

- Shell commands run with:
  - explicit timeout handling
  - best-effort termination for hung processes
  - optional truncation of stdout/stderr
- Workspace git commands avoid exposing auth tokens on the CLI.

**Relevant module:** `github_mcp/workspace.py`

### 3.5 Caching and data minimization

- File cache is in-memory only and bounded by entry count and byte size.
**Relevant modules:**
- `github_mcp/file_cache.py`
- `github_mcp/mcp_server/schemas.py` (metadata sanitation)

### 3.6 Health

- `/healthz` reports whether a GitHub token is present.
**Relevant modules:**
- `github_mcp/http_routes/healthz.py`

### 3.8 HTTP response caching controls

- Dynamic endpoints (`/sse`, `/messages`) are served with `Cache-Control: no-store`.
- Static assets can be cached long-term.

**Relevant module:** `main.py` (`_CacheControlMiddleware`)

## 4. Notable safety gaps or assumptions

1. **Write enforcement is metadata-only.**
   - Runtime authorization checks are not enforced in tool implementations.
   - If enforcement is desired, it must be added or enforced upstream.

2. **No UI approval prompts.**
   - The server does not enforce approvals at runtime.
   - Clients should use tool metadata (`approval_required`, `ui_prompt`) to determine whether to prompt/confirm.

3. **Security posture relies on environment trust.**
   - The server assumes that environment variables and process isolation are controlled by deployment.
   - In this project, production deployment is Render.com only; security posture and isolation assumptions are therefore tied to Render service configuration.

These are not necessarily flaws, but they are important operational assumptions for safe use.

## 5. Recommended follow-up checks (operational)

- Ensure deployment has strong boundary controls around `GITHUB_MCP_WRITE_ALLOWED` / `WRITE_ALLOWED` and tool exposure.
- Validate that runtime environment is restricted (filesystem and network) per the intended risk profile.
- Confirm log retention policies align with organizational requirements.

---

*Document generated from the codebase in `/workspace/chatgpt-mcp-github`.*

Console output is intentionally short and readable, while preserving structured fields for machine parsing.

- Example start: `tool_call_started tool=terminal_command call_id=... write_action=True`
- Example success: `tool_call_completed tool=terminal_command call_id=... duration_ms=475.12`
- Example failure: `tool_call_failed tool=terminal_command call_id=... phase=execute duration_ms=12.34`

The structured payload is appended to log lines as `data=<json>`.

Canonical fields in the structured payload:

- `event`: `tool_call_started` | `tool_call_completed` | `tool_call_failed`
- `tool`
- `call_id`
- `duration_ms` (for completed/failed)
- `phase` (for failed)
- `schema_hash` and `schema_present`
- `write_action`
- `request` (minimal): `path`, `received_at`, `session_id`, `message_id`
- `request.chatgpt` (when present): `conversation_id`, `assistant_id`, `organization_id`, `project_id`, `session_id`, `user_id`
- On failures (when available): `incident_id`, `error_code`, `error_category`, `error_origin`, `error_retryable`, `error_critical`

This separation ensures provider logs stay readable while retaining the complete debug context.
