# Architecture and safety

This document describes the main safety and isolation boundaries in the Adaptiv GitHub MCP server.

The code is the source of truth. If anything in this document diverges from runtime behavior, update the document.

## Boundary: workspace clone

Workspace-backed tools operate on a persistent server-side git clone.

Key properties:

- All workspace paths are resolved under the repository root.
- Workspace file tools reject paths that resolve outside the repo root.
- Directory traversal and absolute-path escapes are blocked by realpath checks.

## Boundary: bounded command execution

The server exposes controlled command execution for the workspace clone via tools such as `terminal_command`.

Safety properties:

- Commands run inside the workspace clone directory.
- Tool invocations carry metadata that allows request deduplication and correlation.
- Output returned to the client is bounded by explicit truncation logic (see the tool schemas for the exact limits and parameters).

Important: the tool surface is authoritative for what is allowed. Prefer the tool catalog (`Detailed_Tools.md`) to infer exactly which operations are exposed.

## Boundary: bounded workspace search

The `search_workspace` tool performs a bounded, non-shell search over text files in the workspace clone.

- `query` is always treated as a literal substring match.
- `regex`, `max_results`, and `max_file_bytes` are accepted for compatibility/observability but are not enforced as output limits.
- Probable binaries are skipped (null-byte check over an initial sample).

## Boundary: write gating

Write actions are classified in the tool registry (`write_action: true`).

The environment variable `GITHUB_MCP_WRITE_ALLOWED` controls whether write actions are auto-approved.

- When true: write tools are auto-approved.
- When false: the tool surface remains available, but clients should prompt/confirm before invoking write tools.

Tool listings expose `approval_required` so clients can implement consistent gating.

## Boundary: network egress

Network calls are primarily to GitHub’s API base URL, with optional override via `GITHUB_API_BASE`.

The server uses a shared HTTPX client with explicit timeouts and concurrency controls. See `docs/usage.md` for the supported tuning variables.

## Observability

The server provides `/healthz` for a small health payload (uptime, controller defaults, token-present signal).

Additional introspection tools (for example `list_all_actions`) expose the effective tool surface.
