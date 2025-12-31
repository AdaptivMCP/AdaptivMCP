# Adaptiv Controller (GitHub MCP) Architecture & Safety Review

This document describes the architecture and safety posture of the Adaptiv Controller GitHub MCP server based on a review of the code modules. It maps core subsystems to their implementation files and calls out security/safety considerations surfaced in the code.

## 1. High-level architecture

The server is an ASGI application that exposes a Model Context Protocol (MCP) tool surface for GitHub operations and local workspace tooling. The implementation combines:

- **Entry-point ASGI app**: `main.py`
- **Core MCP server plumbing**: `github_mcp/mcp_server/*`
- **Tool families**: `github_mcp/main_tools/*` and `github_mcp/workspace_tools/*`
- **GitHub API clients + caching**: `github_mcp/http_clients.py`, `github_mcp/github_content.py`, `github_mcp/file_cache.py`
- **Observability + metrics**: `github_mcp/metrics.py`, `github_mcp/tool_logging.py`, `github_mcp/http_routes/healthz.py`

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
          ├─ Tool call logging + metrics
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
    - **Request context**: extracts `session_id` and MCP JSON-RPC `id` for dedupe/logging.
  - Registers HTTP routes (health check, actions compat routes).
  - Exposes tool definitions and metadata through imported tool modules.

### 2.2 Core MCP server glue

- **`github_mcp/mcp_server/context.py`**
  - Initializes `FastMCP` instance and shared contextvars for request metadata.
  - Defines the write-allowed flag (`WRITE_ALLOWED`), tool examples, and recent tool event buffer.
  - Wraps MCP session response to suppress SSE disconnect noise.

- **`github_mcp/mcp_server/decorators.py`**
  - Implements the `@mcp_tool` decorator:
    - Registers tools with FastMCP while keeping Python-callable functions.
    - Adapts registration to FastMCP tool signature variants (with or without tag support).
    - Logs structured tool lifecycle events.
    - Tracks metrics and recent tool events.
    - Performs best-effort dedupe to avoid double execution on retries.
  - Calculates side-effect class for each tool.
  - Explicitly disables UI approval prompts (`_ui_prompt_required_for_tool` returns `False`).

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

### 2.6 Observability and health

- **`github_mcp/metrics.py`**
  - In-memory counters and timing metrics for tool and GitHub requests.

- **`github_mcp/tool_logging.py`**
  - Structured logging for GitHub API requests with URLs and derived human-friendly web URLs.

- **`github_mcp/http_routes/healthz.py`**
  - `/healthz` endpoint reporting uptime, token presence, controller defaults, and metrics snapshot.

## 3. Safety & security evaluation

### 3.1 Authentication and secret handling

- GitHub tokens are read from environment variables (`GITHUB_PAT`, `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_OAUTH_TOKEN`).
- Token usage is localized to request helpers; tokens are **not** stored in files.
- Git authentication for `git` commands uses `GIT_HTTP_EXTRAHEADER` and config env injection, keeping secrets out of CLI arguments.

**Relevant modules:**
- `github_mcp/http_clients.py` (`_get_github_token`)
- `github_mcp/workspace.py` (`_git_auth_env`)

### 3.2 Write allow-listing & approvals

- A write-allowed flag (`WRITE_ALLOWED`) is exposed via configuration and used for tool metadata.
- UI approval prompts are explicitly disabled in the tool decorator.

**Implication:**
- Write safety is *metadata-based* and depends on operator configuration or external policy.

**Relevant modules:**
- `github_mcp/mcp_server/context.py` (`WRITE_ALLOWED`)
- `github_mcp/mcp_server/decorators.py` (`_ui_prompt_required_for_tool` returns `False`)

### 3.3 Side-effect classification

Tools are classified as:
- **READ_ONLY**
- **LOCAL_MUTATION** (workspace changes)
- **REMOTE_MUTATION** (GitHub writes)

This classification is used for logging, metadata, and recent event buffers.

**Relevant module:** `github_mcp/side_effects.py`

### 3.4 Dedupe and retry behavior

- Tool calls are de-duplicated in-memory to mitigate retry storms.
- GitHub API calls are retried with backoff when rate limits are detected.
- Git operations are retried for rate-limit error messages.

**Relevant modules:**
- `github_mcp/mcp_server/decorators.py` (dedupe)
- `github_mcp/http_clients.py` (API retry/backoff)
- `github_mcp/workspace.py` (`_run_git_with_retry`)

### 3.5 Command execution safeguards

- Shell commands run with:
  - explicit timeout handling
  - best-effort termination for hung processes
  - optional truncation of stdout/stderr
- Workspace git commands avoid exposing auth tokens on the CLI.

**Relevant module:** `github_mcp/workspace.py`

### 3.6 Caching and data minimization

- File cache is in-memory only and bounded by entry count and byte size.
- Metrics and recent tool events are in-memory only; they reset on restart.
- Log payloads are structured for readability and to avoid excessive verbosity.

**Relevant modules:**
- `github_mcp/file_cache.py`
- `github_mcp/metrics.py`
- `github_mcp/mcp_server/context.py` (recent events)
- `github_mcp/mcp_server/schemas.py` (metadata sanitation)

### 3.7 Health and observability

- `/healthz` reports whether a GitHub token is present.
- Health payload includes current metrics snapshot and controller defaults.
- GitHub API logs include web URLs for operator-friendly debugging.

**Relevant modules:**
- `github_mcp/http_routes/healthz.py`
- `github_mcp/tool_logging.py`

### 3.8 HTTP response caching controls

- Dynamic endpoints (`/sse`, `/messages`) are served with `Cache-Control: no-store`.
- Static assets can be cached long-term.

**Relevant module:** `main.py` (`_CacheControlMiddleware`)

## 4. Notable safety gaps or assumptions

1. **Write enforcement is metadata-only.**
   - Runtime authorization checks are not enforced in tool implementations.
   - If enforcement is desired, it must be added or enforced upstream.

2. **No UI approval prompts.**
   - The server explicitly disables UI approval prompts for tool invocations.

3. **Security posture relies on environment trust.**
   - The server assumes that environment variables and process isolation are controlled by deployment.

These are not necessarily flaws, but they are important operational assumptions for safe use.

## 5. Recommended follow-up checks (operational)

- Ensure deployment has strong boundary controls around `WRITE_ALLOWED` and tool exposure.
- Validate that runtime environment is restricted (filesystem and network) per the intended risk profile.
- Confirm log retention policies align with organizational requirements.

---

*Document generated from the codebase in `/workspace/chatgpt-mcp-github`.*

## Tool-event logging

The server emits structured tool lifecycle events to provider logs (e.g., Render) to make debugging and auditing straightforward.

Each tool call emits up to three events:

- `tool_call.start` — emitted after preflight validation but before execution
- `tool_call.ok` — emitted after successful execution
- `tool_call.error` — emitted on exceptions

Console output is intentionally short and readable:

- Example: `[tool] terminal_command ok 475ms (tool_call.ok)`

The full structured payload is attached as a compact JSON string under the log extra field `tool_json`.

Canonical fields in the structured payload:

- `event`: `tool_call.start` | `tool_call.ok` | `tool_call.error`
- `status`: `start` | `ok` | `error`
- `tool_name`
- `call_id`
- `duration_ms` (for ok/error)
- `schema_hash` and `schema_present`
- `write_action` and `write_allowed`
- `request` (minimal): `path`, `received_at`, `session_id`, `message_id`

This separation ensures provider logs stay readable while retaining the complete debug context.
