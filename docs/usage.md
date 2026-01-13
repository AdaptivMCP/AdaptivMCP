# Adaptiv GitHub MCP server usage

This document describes the current functionality, behavior, and usage
patterns for the GitHub MCP (Model Context Protocol) server.

## Key concepts

1) Repository clone (persistent)

When you use any workspace-backed tool, the server maintains a persistent git clone of the target repository on the server filesystem. This clone is what workspace tools operate on (editing files, running commands, committing, and pushing).

Important: the persistent clone is not the live GitHub state. It is a local copy that becomes “live” on GitHub after you push.

2) Server “workspace”

In this project’s terminology, “workspace” refers to the server-side environment where the persistent clone lives and where commands run. It can be thought of as a stable working directory plus the repo clone.

Because the workspace holds the clone, the two terms are closely related, but the clone is the source of truth for edits, while GitHub remains the source of truth for the remote state.

3) GitHub API tools vs workspace tools

- Workspace tools: operate on the persistent clone (local filesystem + git).
- GitHub API tools: inspect or mutate GitHub’s remote state (issues, PRs, Actions, contents API, etc.).

## Write gate (auto-approval)

This server supports approval-gated write actions. The environment variable `GITHUB_MCP_WRITE_ALLOWED` controls whether write actions are auto-approved.

- `GITHUB_MCP_WRITE_ALLOWED=true`: write tools are auto-approved.
- `GITHUB_MCP_WRITE_ALLOWED=false`: write tools remain executable, but some clients may prompt or gate before invoking write tools.

Introspection and actions-compat listings expose:

- `write_action`: tool is classified as a write.
- `write_allowed`: tool is executable (approval-gated writes still execute).
- `write_actions_enabled` / `write_auto_approved`: writes are auto-approved.
- `approval_required`: clients may prompt or gate before invoking the tool.

## What this server provides

- MCP tool surface for GitHub operations: repositories, issues, PRs, actions, files
- Workspace-backed commands for local edits (via the persistent clone)
- Health diagnostics via /healthz

For a complete tool catalog and schemas, see `Detailed_Tools.md`.

## Runtime endpoints

The ASGI application is exposed in `main.py` as `app`.

- GET /sse — MCP transport endpoint (SSE)
- POST /messages — MCP message submit endpoint used by the SSE transport
- GET /healthz — JSON health status and controller defaults
- GET /tools — tool registry for discovery
- GET /resources — resource listing for MCP clients expecting a resource-only response
- GET /tools/<name> — tool metadata (always includes parameters)
- POST /tools/<name> — tool invocation endpoint
- GET /v1/actions and GET /actions — Actions-compatible tool listing
- GET /ui and GET /ui.json — lightweight UI diagnostics (serves `assets/index.html` when present)
- GET /static/* — static assets (if `assets/` is present)

## Recommended workflows

### Read-only workflows

GitHub API read tools cover discovery and inspection, such as:

- get_repo_defaults, get_server_config, validate_environment
- list_recent_issues, list_repository_issues, fetch_issue
- fetch_pr, get_pr_info, list_pr_changed_filenames

If REST helpers are blocked by client safety gating, the GraphQL fallbacks cover the same scenarios:

- list_open_issues_graphql
- list_workflow_runs_graphql, list_recent_failures_graphql
- get_repo_dashboard_graphql

### Edit workflows (clone-first)

Edits are typically done in the persistent clone.

Typical flow:

1. Prepare or reuse the clone
   - `ensure_workspace_clone` creates or reuses the persistent clone.
   - `workspace_sync_status` reports whether the clone is ahead/behind or has uncommitted changes.

2. Make changes in the clone
   - Edit files using workspace file tools or shell editors.
   - Validate changes using your normal commands (tests, linters, etc.).

3. Commit and push from the clone
   - `terminal_command` (or the higher-level git helpers) runs:
     - git add
     - git commit
     - git push

4. Refresh when you need a clean snapshot
   - The local clone does not automatically reflect the live GitHub state unless you fetch/pull or recreate the clone.
   - To align the clone with a branch’s remote state, `workspace_sync_to_remote` updates it.
   - As a last resort, `ensure_workspace_clone(reset=true)` re-clones.

### GitHub API usage guidance

Because the clone is not the live GitHub state, GitHub API tools are typically used for:

- Workspace tools for changes, followed by push.
- GitHub API tools to confirm live state (PR status, CI, branch contents, etc.).
- Re-sync/re-clone when the clone needs to match GitHub exactly (for example, after a merge or force-update).

## Behavior notes

- Workspace persistence: the persistent clone survives across tool calls until explicitly deleted or overwritten.
- Request deduplication: the server uses request metadata (session + message) to avoid duplicate tool execution.
- ChatGPT metadata: the server captures safe ChatGPT headers (conversation, assistant, project, org, session, user IDs) for correlation and includes them in request context/logging.
- Cache control: dynamic endpoints are served with `Cache-Control: no-store`; static assets under `/static` are cacheable.
- File caching: GitHub file contents may be cached in-memory to reduce repeated fetches.

## Deployment (Render.com)

Adaptiv MCP is deployed through Render.com as a web service. Production deployments are managed via Render (build + deploy + environment variables). Local execution supports development and testing.

Render-specific notes:

- Render injects `PORT` automatically; the process binds to `$PORT`.
- Configure GitHub authentication via Render environment variables (for example `GITHUB_TOKEN`).
- `/healthz` reports token detection and baseline health after deploy.

## Configuration

### Minimum required configuration

Provide at least one GitHub authentication token so the server can access the API:

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, or GITHUB_OAUTH_TOKEN

For Render integration, set one Render API token so the server can access the Render API:

- RENDER_API_KEY or RENDER_API_TOKEN (first configured token wins; see RENDER_TOKEN_ENV_VARS)

### GitHub authentication

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, GITHUB_OAUTH_TOKEN — GitHub API token (first configured is used)
- GITHUB_API_BASE — override GitHub API base URL

### Controller defaults

- GITHUB_MCP_CONTROLLER_REPO — controller repo full_name (owner/repo)
- GITHUB_MCP_CONTROLLER_BRANCH — controller default branch

### Logging (provider logs)

These flags control provider-side logs (for example, Render logs). They leave tool outputs unchanged.

- HUMAN_LOGS (default: true) — emits scan-friendly tool call log lines with correlation fields.
- LOG_TOOL_PAYLOADS (default: false) — logs full tool input arguments and full tool results (no truncation).
- LOG_GITHUB_HTTP (default: false) — logs outbound GitHub HTTP method/path/status/duration with correlation fields.
- LOG_GITHUB_HTTP_BODIES (default: false) — includes full GitHub response bodies/headers in provider logs.
- LOG_RENDER_HTTP (default: false) — logs outbound Render HTTP method/path/status/duration with correlation fields.
- LOG_RENDER_HTTP_BODIES (default: false) — includes full Render response bodies/headers in provider logs.
- LOG_HTTP_REQUESTS (default: false) — logs inbound HTTP requests to the ASGI server (method/path/status/duration) with request_id.
- LOG_HTTP_BODIES (default: false) — when enabled, logs the POST /messages body (no truncation). This may include sensitive payloads.

HTTP exception logging
~~~~~~~~~~~~~~~~~~~~~~

When LOG_HTTP_REQUESTS is enabled, unhandled exceptions inside the ASGI request path are logged as `http_exception`

- LOG_TOOL_CALLS (default: false) — logs tool_call_started/tool_call_completed lines to provider logs. Failures are still logged as warnings.
with request_id/session_id/message_id and a full stack trace.

### Tests

- GITHUB_MCP_ENABLE_SYNTHETIC_GITHUB (default: false) — when running unit tests (PYTEST_CURRENT_TEST is set),
  enables deterministic synthetic GitHub responses for this repository. Not enabled outside tests.
- GITHUB_REPO_DEFAULTS — optional JSON object of repo defaults (to reduce API calls). Supported shapes:
  - {"owner/repo": {"default_branch": "main"}}
  - {"owner/repo": "main"} (shorthand)

### Write gate (auto-approval)

- GITHUB_MCP_WRITE_ALLOWED — when true, write tools are auto-approved; when false, clients may prompt (see Write gate section in this document)

### Tool metadata verbosity

- GITHUB_MCP_COMPACT_METADATA_DEFAULT — default for whether tool listings return compact metadata

### Workspace settings

- MCP_WORKSPACE_BASE_DIR — base directory for persistent workspace clones
- MCP_WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS — timeout for applying diffs to the workspace clone

### File cache (GitHub content fetches)

- FILE_CACHE_MAX_ENTRIES — max number of cached file entries
- FILE_CACHE_MAX_BYTES — max total bytes for cached file contents

### Concurrency and timeouts

- HTTPX_TIMEOUT, HTTPX_MAX_CONNECTIONS, HTTPX_MAX_KEEPALIVE
- MAX_CONCURRENCY, FETCH_FILES_CONCURRENCY

### GitHub rate limiting and search pacing

- GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS
- GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS
- GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS
- GITHUB_SEARCH_MIN_INTERVAL_SECONDS

### Sandbox/content rewrite (optional)

- SANDBOX_CONTENT_BASE_URL — optional base URL used when rewriting content paths for sandboxed environments

### Logging

- LOG_LEVEL
- LOG_FORMAT

## Local development

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Once running, /sse serves the MCP transport and /healthz reports health.

## Troubleshooting tips

- `validate_environment` reports GitHub token detection and defaults.
