# Hint logic, behaviors, and functionality

This document maps how the server derives and surfaces hints. “Hints” here are
structured, optional guidance fields that explain *why* something failed or how
UIs should label tool capabilities. They are kept separate from primary error
messages so clients can display them without duplicating or looping the main
message.

## 1. Hint surfaces (where hints appear)

### 1.1 Structured error payloads
* The error handling pipeline collects `hint` from exceptions (if present) and
 injects it into the `error_detail` envelope returned by tools and routes. This
 happens alongside standardized fields like `category`, `code`, `details`, and
 `origin`.
* The tool registry normalizes responses so that **hints survive even when tools
 return partial/bare error payloads**. If a tool returns `{error, error_detail}`
 or a bare `error_detail`, any `hint` field is preserved and placed in the final
 error envelope.

### 1.2 UI annotations for tool discovery
* Tool annotations include `readOnlyHint` and `openWorldHint`. These are UI
 badges used by MCP clients for discovery and labeling rather than runtime
 gating. The annotations are attached via the tool decorator pipeline and can
 be updated per-invocation.
* Auto-approve mode suppresses **all** UI hints by forcing both hint flags to
 `False`, preserving stable READ/WRITE tagging while avoiding extra UI badges.


### 1.3 Routing hints
* Routing hints are a separate structured field (e.g., `routing_hint`) that can
 be attached to error payloads, allowing downstream callers to act on routing
 signals without changing the user-visible error message. This is treated
 independently from the human-facing `hint` string.

## 2. Error hint logic (detailed mapping)

### 2.1 Exception types that can carry hints
* `ToolOperationError` (and related custom exceptions) can include `hint` as a
 constructor parameter. This is a first-class field that is later surfaced
 through the structured error pipeline.

### 2.2 Workspace patch apply errors
* When applying patches, failures are categorized and can emit a **specific hint
 for malformed hunks**. If the patch contains bare `@@` separators without line
 ranges, a hint explains correct unified diff formatting or the MCP tool patch
 format. The hint is stored in `exc.hint` and kept separate from the main error
 text to avoid repetition/looping by clients.

### 2.3 Sandbox/local file path handling (content_url)
* When reading `content_url` paths, missing files can emit a hint explaining the
 `sandbox:/` prefix convention. This hint is attached to the error without
 duplicating the primary error message, and it’s preserved even if the server
 rewrites paths for sandbox access.

### 2.4 Default hint inference (fallback behavior)
* If an exception does not specify a hint, the error handler can **infer default
 hints** for common problems (e.g., missing file paths). These defaults are only
 applied when no explicit hint is present, ensuring explicit hints take
 precedence.

## 3. UI hint logic (tool annotations)

### 3.1 Default hinting rules
* `readOnlyHint` defaults to `True` when a tool is not a write action; otherwise
 it defaults to `False`.
* `openWorldHint` defaults to `True` because tools generally interact with
 external systems (filesystem/network/hosted providers).

### 3.2 Invocation-time annotation updates
* During tool invocation, annotations are refreshed dynamically based on the
 **effective write action** for that call. This allows tools that change between
 read/write modes to surface accurate UI badges per invocation.
* If a tool was previously marked as write-capable, later read-only invocations
 **will not overwrite** a `readOnlyHint=False` annotation. This avoids UI
 flapping and preserves conservative labeling for tools that can write.


## 4. Behavioral guarantees and client experience

* **Hints are additive, not duplicative.** They are stored in a dedicated field
 and intentionally excluded from the primary error message so clients can
 render them separately without repeating the core error text.

* **Hints survive normalization.** Even if tools return partial or legacy error
 structures, the tool registry normalizes output so hints remain available to
 callers.
* **UI hints are informational only.** They are surfaced as annotations for
 discovery/badging and do not change runtime permission checks.


## 5. Related safety behavior (context for hints)

Hints are part of a broader safety and diagnostics strategy. For example, the
error handler also categorizes errors and sanitizes validation/debug payloads to
avoid upstream safety blocks while still providing actionable guidance.

