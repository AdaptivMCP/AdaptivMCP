# Adaptiv MCP Hinting Logic

This document maps where Adaptiv MCP emits structured hints, how those hints are
computed, and where they are surfaced (tool discovery, UI badges, structured
errors, and diagnostics outputs).

## 1) Hint channels and payload shapes

Adaptiv MCP uses multiple *hint channels* depending on the surface:

1. **Tool discovery/UI annotations**: boolean hints that drive MCP tool badges
   (`readOnlyHint`, `destructiveHint`, `openWorldHint`). These appear in tool
   metadata and are meant for UIs and safety gating visuals.【F:github_mcp/mcp_server/decorators.py†L1768-L1830】
2. **Structured error hints**: string hints attached to exceptions or returned
   in error payloads; they land in `error_detail.hint` for clients to render or
   surface separately from the main message.【F:github_mcp/mcp_server/error_handling.py†L196-L401】
3. **Diagnostics/metadata hints**: non-error hints included in tool outputs
   (e.g., token scope explanations).【F:github_mcp/main_tools/env.py†L540-L610】
4. **Validation suggestions**: structured warning + detail payloads that help
   callers fix malformed arguments (not strictly “hint” fields, but used in the
   same remediation flow).【F:github_mcp/mcp_server/suggestions.py†L260-L323】

The sections below detail each channel and how hints propagate.

## 2) Tool annotation hints (UI + discovery)

### 2.1 Defaulting logic

The helper `_tool_annotations` computes MCP hint booleans with defaults based on
`write_action`:

- `readOnlyHint` defaults to `not write_action`.
- `destructiveHint` defaults to `write_action`.
- `openWorldHint` defaults to `True` (tools interact outside the model).
- If auto-approve is enabled, all hint booleans are suppressed so UI clients
  don’t render badges (annotations remain structurally present).【F:github_mcp/mcp_server/decorators.py†L1768-L1828】

### 2.2 Author overrides

The `mcp_tool` decorator accepts `open_world_hint`, `destructive_hint`, and
`read_only_hint` so tool authors can override defaults at registration time. The
wrapper stores those values as `__mcp_*_hint__` attributes for later use and
registers the tool with the computed annotations.【F:github_mcp/mcp_server/decorators.py†L3795-L3945】【F:github_mcp/mcp_server/decorators.py†L4200-L4245】

### 2.3 Per-invocation refresh

At invocation time, Adaptiv MCP recomputes annotations using any stored
`__mcp_*_hint__` overrides and the *effective* `write_action` (which can be
resolved dynamically per call). The refresh path updates the tool object’s
annotations with best-effort safety to avoid overwriting an explicitly
`destructiveHint=True`/`readOnlyHint=False` on read-only invocations.【F:github_mcp/mcp_server/decorators.py†L1832-L1916】

### 2.4 UI badge rendering + filtering

The tool catalog UI reads these annotations to render badges like `OPEN WORLD`
and `DESTRUCTIVE`, and allows filtering by destructive tools using the same
fields. The UI always renders a READ/WRITE badge based on `write_action`, then
adds hint badges if `openWorldHint` or `destructiveHint` are true.【F:github_mcp/http_routes/ui.py†L188-L247】

## 3) Structured error hints

### 3.1 Generic structured error assembly

`_structured_tool_error` is the central aggregator for error payloads. It:

- Reads `.hint` from the exception (if present) and emits it as
  `error_detail.hint`.
- Normalizes categories/codes (e.g., `not_found`, `permission`, `validation`) and
  adds retryability flags and details.
- Passes through `routing_hint` when provided (this is a route/connector
  metadata hint for clients).【F:github_mcp/mcp_server/error_handling.py†L196-L418】

Any exception carrying `.hint` (including custom `ToolOperationError` fields) is
preserved in the final error detail payload.【F:github_mcp/exceptions.py†L71-L106】【F:github_mcp/mcp_server/error_handling.py†L234-L401】

### 3.2 Hint injection sites

A few key places add `.hint` explicitly before `_structured_tool_error` runs:

- **Write approval gating**: `_enforce_write_allowed` raises
  `WriteApprovalRequiredError` and sets a hint that explains how to approve or
  enable auto-approve.【F:github_mcp/mcp_server/decorators.py†L1996-L2014】
- **Workspace patch application**: patch parsing failures can append a hint
  explaining correct unified diff hunk headers (e.g., `@@ -1,3 +1,3 @@`). The
  hint is attached to a `GitHubAPIError` so clients see remedial guidance
  separately from the failure message.【F:github_mcp/workspace.py†L1269-L1324】
- **Sandbox/local content URLs**: when local or sandbox content URLs are missing
  or improperly prefixed, the loader attaches hints about using `sandbox:/` or
  configuring `SANDBOX_CONTENT_BASE_URL`. This keeps guidance out of the primary
  error message and avoids repetitive retries.【F:github_mcp/github_content.py†L249-L348】

### 3.3 Normalization for HTTP tool results

When a tool returns a partial error payload or a bare `error_detail`, the HTTP
layer normalizes it and **preserves `hint`** values by copying them into
`error_detail.hint` within a stable envelope. This ensures client code always
gets hints in a consistent location even for tools that return errors instead of
raising them.【F:github_mcp/http_routes/tool_registry.py†L220-L296】

## 4) Validation suggestions (non-error hints)

When tool argument validation fails, the suggestions layer appends warnings and
structured `details` (expected args, unknown args, missing args). This is not
stored in the `hint` field, but it serves the same purpose—guiding callers to
fix input issues and avoid retries with invalid payloads.【F:github_mcp/mcp_server/suggestions.py†L260-L323】

## 5) Diagnostics hints in tool output

The `env` diagnostics tool collects token metadata and includes `scope_hints`
for classic PAT scopes (e.g., `repo`, `workflow`) to explain what those scopes
permit. These hints are included in the tool’s structured output to help
operators quickly identify missing permissions.【F:github_mcp/main_tools/env.py†L540-L610】

## 6) Summary: end-to-end hint flow

1. **Tool registration** attaches annotation hints based on `write_action` and
   explicit overrides. These annotations flow to MCP discovery payloads and the
   web UI for badges and filtering.【F:github_mcp/mcp_server/decorators.py†L1768-L1830】【F:github_mcp/http_routes/ui.py†L188-L247】
2. **Tool invocation** may dynamically refresh annotations based on runtime
   write classification, maintaining accurate hints even with
   `write_action_resolver` logic.【F:github_mcp/mcp_server/decorators.py†L1832-L1916】
3. **Failures** attach `hint` strings at the source (approval gating, patch
   parsing, sandbox URL resolution, etc.), and `_structured_tool_error` promotes
   them into `error_detail.hint` so client UIs can render guidance separately
   from the main error message.【F:github_mcp/mcp_server/decorators.py†L1996-L2014】【F:github_mcp/workspace.py†L1269-L1324】【F:github_mcp/github_content.py†L249-L348】【F:github_mcp/mcp_server/error_handling.py†L196-L418】
4. **HTTP wrappers** normalize tool-returned errors and preserve hints to ensure
   a stable error envelope across tools.【F:github_mcp/http_routes/tool_registry.py†L220-L296】
5. **Diagnostics/validation** surfaces supplemental hints via warnings and
   metadata for easier remediation without relying on raw error strings.
   【F:github_mcp/mcp_server/suggestions.py†L260-L323】【F:github_mcp/main_tools/env.py†L540-L610】
