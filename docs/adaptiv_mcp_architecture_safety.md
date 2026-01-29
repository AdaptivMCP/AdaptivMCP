# Adaptiv MCP Architecture & Safety

## Overview

Adaptiv MCP is a self-hosted Model Context Protocol (MCP) server that exposes
GitHub, workspace, and Render automation tools via HTTP endpoints. It combines
an ASGI web application with a tool registry so MCP clients can discover tools,
invoke them, and receive structured responses.

This document maps the runtime architecture and the safety controls embedded in
key layers.

## Architecture

### 1. Runtime entrypoint and HTTP surface

- **ASGI entrypoint**: `main.py` builds the ASGI app (FastMCP-backed where
  available) and falls back to a plain Starlette app when needed. The server
  exposes SSE transport (`/sse`) for MCP connections and mounts static assets
  under `/static`.【F:main.py†L726-L807】
- **Middleware**:
  - `_CacheControlMiddleware` applies no-store caching headers to dynamic
    endpoints while allowing immutable caching of static assets to prevent
    sensitive responses from being cached by proxies.【F:main.py†L102-L164】
  - `_RequestContextMiddleware` captures request IDs, idempotency keys, and
    session metadata for logging and de-duplication in downstream tool
    handlers.【F:main.py†L167-L260】
- **HTTP routes**: Route registration wires the tool registry, UI, Render, LLM
  execution, session, and health endpoints onto the app instance.【F:main.py†L813-L818】

### 2. Tool registration and discovery

- **Tool registration**: Tool functions are registered via `@mcp_tool`, which
  binds a callable into the registry, generates an input schema, and ensures
  structured error payloads. The public server surface exports this decorator
  and the registry hooks for discovery/introspection.【F:github_mcp/server.py†L1-L47】
- **Tool discovery**: The HTTP tool registry builds a catalog of tools and
  resource URIs for clients to discover available actions; it deliberately
  returns relative URIs to avoid stale links when the server is mounted under
  temporary path prefixes.【F:github_mcp/http_routes/tool_registry.py†L44-L108】
- **Workspace tool surface**: `github_mcp.tools_workspace` eagerly imports all
  workspace tool modules so every `@mcp_tool`-decorated function is registered
  and available for MCP clients and HTTP callers.【F:github_mcp/tools_workspace.py†L18-L63】

### 3. Tool domains and subsystems

- **Main tools**: GitHub-oriented tools live under `github_mcp/main_tools` and
  are registered at import time (for example, repository, issue, or PR helpers).
- **Workspace tools**: Workspace mirror tools expose local repo operations such
  as reading/writing files, running commands, and applying diffs. The
  `tools_workspace` surface re-exports these stable APIs for clients and tests
  while importing every module under `github_mcp.workspace_tools` to ensure
  registration.【F:github_mcp/tools_workspace.py†L18-L148】
- **Render integration**: Render API helpers are encapsulated in
  `github_mcp/render_api.py`, which enforces real API responses and readable
  logs as design goals for Render tooling.【F:github_mcp/render_api.py†L1-L16】

### 4. Error and response normalization

- **Structured error envelopes**: The server converts exceptions into
  structured error payloads and makes cancellation a first-class outcome. It
  also sanitizes error details to avoid leaking secrets or oversized payloads.
  【F:github_mcp/mcp_server/error_handling.py†L60-L170】
- **Tool payload shaping**: Tool responses include gating metadata and other
  structured fields so callers can interpret write permissions, warnings, and
  results in a consistent format.【F:github_mcp/mcp_server/decorators.py†L1184-L1242】

## Safety and Control Measures

### 1. Write approval gate

- **Auto-approve gate**: Write operations are governed by environment-based
  auto-approve settings. `get_write_allowed()` consults environment variables
  (e.g., `ADAPTIV_MCP_AUTO_APPROVE`) and only permits write actions by default
  when auto-approve is enabled.【F:github_mcp/mcp_server/context.py†L120-L212】
- **Runtime enforcement**: Tool wrappers enforce write approval when
  auto-approve is disabled, raising a `WriteApprovalRequiredError` if a write
  tool is invoked without explicit approval.

### 3. Patch and write validation

- **Patch validation**: `_apply_patch_to_repo` rejects empty patches and
  categorizes failures with explicit error codes like `PATCH_EMPTY`,
  `PATCH_MALFORMED`, and `PATCH_APPLY_FAILED`, ensuring patch errors are
  explicit and actionable.

### 4. Read safety limits

- **Default read caps**: Workspace file reads use default byte and character
  limits (`_DEFAULT_MAX_READ_BYTES`, `_DEFAULT_MAX_READ_CHARS`) to avoid loading
  overly large files into memory unless the caller explicitly overrides them.

### 5. Log and error redaction

- **Sensitive data filtering**: `_args_summary` intentionally avoids logging
  payload-sized fields and secret-like keys unless `ADAPTIV_MCP_LOG_SENSITIVE`
  is enabled, preventing accidental leakage of tokens or secrets in logs.
- **Error sanitization**: `_sanitize_debug_value` redacts token-like values,
  truncates long strings, and removes high-entropy secret candidates from error
  details to avoid triggering upstream safety filters or leaking secrets.

### 6. Request de-duplication

- **Dedupe control**: `_maybe_dedupe_call` coalesces identical tool invocations
  within a TTL window to prevent duplicate work when upstream clients retry
  requests during long-running operations.

### 7. Cache safety for dynamic responses

- **Cache-control enforcement**: Middleware ensures dynamic HTTP endpoints are
  marked `no-store` while static assets remain cacheable, reducing the risk of
  proxies caching sensitive tool outputs.