# Validation Logic

This document maps the validation logic across the MCP server so operators and
contributors can understand where checks happen, how errors are categorized,
and what output surfaces to expect.

## Overview

Validation is handled in layers:

1. **Tool invocation normalization + preflight**: HTTP requests are normalized
   to a consistent `args` shape before tools execute, with limited preflight
   processing for logging and schema publishing.
2. **Tool-level checks**: Individual tools raise `ValueError`, `TypeError`, or
   `UsageError` when inputs are missing or malformed.
3. **Workspace/patch validation**: Patch application and file operations convert
   known failure modes into explicit validation categories/codes.
4. **Structured error mapping**: Exceptions are normalized into structured
   payloads and HTTP status codes, with validation errors sanitized to avoid
   leaking sensitive data.
5. **Environment validation**: A dedicated tool (`validate_environment`) returns
   operator-friendly checks for runtime configuration.

## Tool invocation normalization

### HTTP payload normalization

The HTTP tool registry normalizes incoming payloads into a plain dict of tool
arguments. It supports JSON-RPC-style envelopes as well as common wrapper
shapes such as `args`, `arguments`, `parameters`, or `input`. Metadata fields
like `_meta` are stripped so tools only receive user arguments.

This happens in `_normalize_payload` (and helpers such as `_extract_wrapped_args`
and `_coerce_json_args`).【F:github_mcp/http_routes/tool_registry.py†L207-L359】

### Tool argument preflight (logging only)

Preflight processing exists to safely serialize arguments for logging and
introspection without mutating them. `_preflight_tool_args` is intentionally a
no-op transformation that just ensures JSON-serializable output, and is used
when building request context for provider logs.【F:github_mcp/mcp_server/schemas.py†L913-L932】【F:github_mcp/mcp_server/decorators.py†L2766-L2798】

### Schema publishing + minimal validation

The introspection tool `_validate_single_tool_args` produces a tool’s input
schema and performs minimal shape validation: payloads must be objects. Schema
validation itself is intentionally **not** enforced server-side; clients are
expected to use the published schema for self-validation.【F:github_mcp/main_tools/introspection.py†L585-L635】

Schema generation is centralized in `_schema_for_callable`, which derives a
best-effort JSON schema from a callable signature or tool metadata and
normalizes it into a JSON-serializable mapping.【F:github_mcp/mcp_server/schemas.py†L880-L912】

## Tool-level validation patterns

Most tools enforce input checks inline by raising `ValueError`, `TypeError`, or
`UsageError`. Examples include:

- `describe_tool` validates argument counts and tool names before returning
  tool metadata.【F:github_mcp/main_tools/introspection.py†L536-L583】
- Render tools validate required parameters like `service_id` and ensure list
  payloads are non-empty objects before forwarding to the Render API.【F:github_mcp/main_tools/render.py†L456-L503】

`UsageError` is a dedicated exception type for user-facing validation failures
that should surface as clear, single-line messages.【F:github_mcp/exceptions.py†L65-L72】

## Workspace patch validation

Patch application in the workspace layer performs explicit validation for
common patch failures and assigns category/code metadata so errors are stable
for callers. Patch-related failures are categorized as `patch` errors (rather
than validation errors) to make it clear they are resolved by fixing the patch
contents or target paths:

- Empty patches raise a `patch` error with `PATCH_EMPTY`.
- Malformed patches map to `PATCH_MALFORMED`.
- Missing files map to `FILE_NOT_FOUND`.
- Conflicts map to `PATCH_APPLY_FAILED` / `PATCH_DOES_NOT_APPLY`.

This logic lives in `_apply_patch_to_repo` and its supporting helpers.【F:github_mcp/workspace.py†L1155-L1268】

## Structured error normalization

### Exception categorization

`_structured_tool_error` maps exceptions into a stable `{status, ok, error,
error_detail}` payload. The logic:

- Treats `ValueError` / `TypeError` as **validation** errors.
- Maps upstream API errors (`APIError`) to categories based on HTTP status
  (e.g., 400/422 → validation, 404 → not_found, 409 → conflict).
- Uses heuristic parsing for patch-related `GitHubAPIError` messages.
- Sanitizes validation and patch error arguments to avoid leaking token-like data.

See `_structured_tool_error` for the detailed mapping and sanitization
behavior.【F:github_mcp/mcp_server/error_handling.py†L86-L436】

### HTTP status mapping

The HTTP registry converts structured errors into status codes using
`_status_code_for_error`, with an additional layer of category inference
(`_infer_error_category`) for legacy or partial error payloads. Validation
errors map to HTTP 400, permission errors to 403, and so on.【F:github_mcp/http_routes/tool_registry.py†L111-L476】

## Environment validation tool

`validate_environment` produces a structured list of checks with `ok`,
`warning`, or `error` levels. It validates:

- Presence of GitHub tokens (and tracks empty env vars).
- Supported Python version ranges.
- Runtime/platform metadata.
- Optional checks (Render metadata, tool registry, repo status) in later
  sections of the function.

This tool is meant for operator diagnostics and returns a stable report
payload for MCP clients.【F:github_mcp/main_tools/env.py†L79-L174】

## Error types used for validation

Validation behavior is tied to specific exception classes:

- `ToolPreflightValidationError` for preflight failures.
- `UsageError` for user-facing input issues.
- `ToolOperationError` for execution errors that may still carry structured
  metadata (category, code, hint, details).

These exception types are defined in `github_mcp/exceptions.py`.【F:github_mcp/exceptions.py†L50-L108】
