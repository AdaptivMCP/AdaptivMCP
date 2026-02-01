# Adaptiv MCP safety & architecture

## Overview

Adaptiv MCP is an MCP server that exposes GitHub, Render, and workspace-mirror automation through MCP transports and an HTTP tool registry. The entrypoint (`main.py`) builds the ASGI app, mounts MCP transports (`/sse` and `/mcp`), and registers HTTP routes for discovery and diagnostics.

Key building blocks:

- **ASGI app and middleware**
 - The server builds a Starlette app from the MCP SDK and wraps it with request-context, cache-control, and disconnect-handling middleware so transports can remain streaming-safe while maintaining stable request identifiers and no-store caching for dynamic endpoints.
- **Tool registry + HTTP facade**
 - HTTP routes expose `/tools`, `/resources`, `/ui`, and tool invocation endpoints for connector discovery and debugging while reusing the MCP tool catalog under the hood.
- **Tool implementations**
 - MCP tools are registered via decorators and organized into GitHub tools, Render tools, and workspace-mirror tools (the latter backed by a persistent git checkout). The workspace tools are imported eagerly to guarantee their registration for discovery and execution.

## Architecture map

### 1) Entry point and transport wiring

- `main.py` sets up the ASGI app, configures the MCP transports, and adds fallbacks so `/mcp` is safe to probe even when streamable HTTP is unavailable. It also keeps legacy `/sse` + `/messages` behavior compatible with older clients.
- The server provides permissive `OPTIONS`/`GET` fallbacks for transport endpoints to avoid noisy `405` responses from probes and load balancers.

### 2) HTTP routes and discovery surface

- The HTTP registry routes build a stable tool catalog from the MCP registry. It exposes resources with relative `uri` values to avoid reverse-proxy base-path mismatches and adds connector-friendly metadata to discovery payloads.
- Render, health, UI, and session helper routes are registered alongside the tool registry to support diagnostics and connector UI links.

### 3) Tool registration and metadata

- Tools are registered with `@mcp_tool`, which binds functions into the MCP registry, produces schemas, and standardizes error handling for tool calls.
- Workspace tools are eagerly imported to ensure that any tool module decorated with `@mcp_tool` is registered and visible to discovery endpoints.

### 4) External API access

- GitHub API calls run through `github_mcp.http_clients._github_request`, which enforces concurrency limits, optional retries, structured error handling, and log correlation via request context metadata.
- Retry behavior defaults to **idempotent methods** (GET/HEAD/OPTIONS) and treats GraphQL POST as retryable, while non-idempotent writes do **not** retry unless explicitly allowed.

### 5) Workspace mirror

- Workspace tools operate on a persistent git checkout. Patch application supports MCP tool patches and unified diffs, applies a timeout for `git apply`, and surfaces structured error categories on failure.
- Patch application uses a repository-relative path helper to resolve file paths for workspace operations, normalizing incoming paths and rejecting empty paths.

## Safety model

### 1) Write gating and approvals

- Write tools are always present in the catalog, but **runtime enforcement** checks the `WRITE_ALLOWED` gate. When auto-approve is disabled, write calls raise a `WriteApprovalRequiredError` unless a request-scoped approval override is set.
- The auto-approve gate is controlled by environment variables (`ADAPTIV_MCP_AUTO_APPROVE`, `MCP_AUTO_APPROVE`, `AUTO_APPROVE`). The gate value is cached and also used to refresh tool metadata so discovery reflects the current setting.

### 2) Idempotency and deduplication

- Request context captures `session_id`, `message_id`, and `idempotency_key` to correlate retries and reduce duplicate tool calls from upstream clients.
- The tool decorator layer includes dedupe helpers that coalesce identical in-flight tool calls, keeping shared tasks alive even if a caller disconnects, and caching successful results for a TTL window.

### 3) Transport safety and caching

- Cache-control middleware applies `no-store` to dynamic endpoints and avoids overriding streaming endpoints so proxies do not cache tool output or transport responses, reducing stale-data risks.
- Transport endpoints include permissive `OPTIONS` handlers to tolerate preflight/probe traffic without leaking state or returning confusing errors.

### 4) Logging and data minimization

- Log sanitization clips payload sizes, collapses whitespace, and avoids emitting binary data or excessive nested structures unless full-fidelity logging is explicitly enabled via environment variables.
- Request-context snapshots keep diagnostic metadata small by default while still reporting key correlation fields for tracing and debugging.

### 5) HTTP client safety

- GitHub request retries are **disabled** for non-idempotent methods unless explicitly allowed, preventing duplicate writes or side effects during retry storms.
- Rate-limit detection uses headers and response body to decide whether a retry is safe, then emits structured errors with retry hints when retries are not allowed.

### 6) Workspace patch safety

- Patch application rejects empty inputs, supports multiple patch formats, and uses a timeout when invoking `git apply` so long-running operations do not hang indefinitely.
- Patch failures are categorized (validation vs conflict vs not_found) with hints for malformed diffs, improving guardrails for automated clients.

## Operational checklist

- **Transport URL**: Use `/mcp` for streamable HTTP (preferred), `/sse` + `/messages` for legacy clients.
- **Write approvals**: Decide whether `ADAPTIV_MCP_AUTO_APPROVE` should be enabled in production; if disabled, ensure your client can pass explicit approvals.
- **Logging**: Tune `ADAPTIV_MCP_LOG_FULL_FIDELITY` and related log truncation controls to balance debugging with log hygiene.
- **Workspace safety**: Monitor patch application errors and adjust `WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS` to fit repo size and workload characteristics.
