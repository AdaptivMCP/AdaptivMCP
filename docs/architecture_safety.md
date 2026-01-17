# Architecture and safety

This document describes the current architecture and safety posture of the
Adaptiv MCP server.

The code is the source of truth. If anything in this document diverges from
runtime behavior, update the document.

## High-level architecture

The server is an ASGI application (`main.py`) that exposes MCP tools over an SSE
transport (`/sse` + `/messages`). Tool discovery is available via `/tools` and
per-tool metadata endpoints.

The tool surface spans two domains:

1) GitHub API tools
   - Operate directly on GitHub’s remote state using REST and GraphQL.
   - Used for inspection and remote mutations (issues/PRs/workflows, etc.).

2) Workspace tools (repo mirror)
   - Operate on a persistent server-side git working copy (“repo mirror”).
   - Used for filesystem-style edits, command execution, commits, and pushes.

See `docs/terminology.md` for precise definitions.

## Safety model

### Tool classification

Tools are labeled with `write_action: true` in the tool registry when they
perform side effects (e.g., writing files, pushing commits, creating PRs,
triggering deploys). Read-only tools omit this flag.

The server does not hard-block write tools at runtime. Clients are expected to
use `write_action` to implement confirmation UX and to ensure user intent is
captured before invoking side-effectful operations.

### Workspace path safety

Workspace file operations validate that paths are repository-relative and
resolve within the repo root. Path traversal and attempts to write outside the
repo mirror are rejected.

Deletion and directory operations are guarded:

- Deletion helpers require a non-empty `paths` list.
- Recursive directory deletion requires `allow_recursive=true`.

### Idempotency and retries

The server captures request context fields (request/session/message IDs and an
optional idempotency key) to support best-effort deduplication across client
retries. Dedupe is intended to reduce accidental duplicate side effects (e.g.,
double commits or duplicate PR creation) when a client retries after timeouts.

### Output shaping vs provider logs

Tool outputs are client-facing. Provider logs (e.g., Render logs) are
operator-facing.

The server supports an optional client-facing response shaping mode intended
primarily for ChatGPT-hosted connectors. When enabled, it normalizes result
envelopes (`ok` / `status`) and bounds overly-large fields.

Response shaping is controlled by environment variables and may auto-enable for
requests that include ChatGPT connector metadata.

## Transport and hosting assumptions

This project is commonly deployed behind a trusted reverse proxy (e.g., Render).
Some transport security enforcement may be relaxed to avoid blocking internal
tooling. Platform-level security controls remain in effect.

## Diagnostics

The `validate_environment` tool provides an operator-friendly report including:

- GitHub/Render token detection
- runtime and deployment signals
- tool registry sanity checks
- optional installed dependency snapshot

Use `validate_environment` in production to confirm all tool surfaces are
registered and that the service can reach GitHub/Render.

