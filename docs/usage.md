# Adaptiv MCP server usage

This document describes the current functionality, behavior, and usage
patterns for the Adaptiv MCP (Model Context Protocol) server.

Adaptiv MCP exposes GitHub and Render tool surfaces over MCP. It supports two
complementary approaches for repository work:

- GitHub API tools operate directly against GitHub's remote state.
- Workspace tools operate on a persistent server-side git working copy (the
  "repo mirror").

## Key concepts

This document uses a small set of terms with specific meanings. See
`docs/terminology.md` for the authoritative glossary.

1) Repo mirror (persistent server-side git working copy)

When you use any workspace-backed tool, the server maintains a persistent git copy of the target repository on the server filesystem. In this documentation, we call that copy the **repo mirror** to avoid confusion with the tool name `ensure_workspace_clone`. The repo mirror is what workspace tools operate on (editing files, running commands, committing, and pushing).

Important: the repo mirror is not the live GitHub state. It is a local copy that becomes “live” on GitHub after you push.

2) Server execution environment

Workspace tools execute on the server runtime (for example, a Render web
service) and operate on the repo mirror stored on the server filesystem.
The execution environment is stable across tool calls until the service is
restarted or the repo mirror is explicitly reset.

3) GitHub API tools vs workspace tools

- Workspace tools: operate on the repo mirror (local filesystem + git).
- GitHub API tools: inspect or mutate GitHub’s remote state (issues, PRs, Actions, contents API, etc.).

## What this server provides

- MCP tool surface for GitHub operations: repositories, issues, PRs, actions, files
- Workspace-backed commands for local edits (via the repo mirror)
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

## Tool groupings

This section lists tool families by capability. It is descriptive only; the
server does not require any particular sequence of tool calls.

### GitHub API tools

Read/inspect:

- get_repo_defaults, get_server_config, validate_environment
- list_recent_issues, list_repository_issues, fetch_issue
- fetch_pr, get_pr_info, list_pr_changed_filenames

GraphQL variants (alternative surfaces for similar inspection operations):

- list_open_issues_graphql
- list_workflow_runs_graphql, list_recent_failures_graphql
- get_repo_dashboard_graphql

### Workspace tools (repo mirror)

Repository working copy management:

- ensure_workspace_clone, workspace_sync_status, workspace_sync_to_remote
- workspace_create_branch

File edits and batch operations:

- set_workspace_file_contents, apply_patch
- apply_workspace_operations (batch write/edit/move/delete)

Command execution:

- terminal_command

Commit/push and PR creation:

- commit_workspace, commit_workspace_files
- commit_and_open_pr_from_workspace

Notes:

- The repo mirror is a persistent server-side working copy; it does not
  automatically match the remote GitHub state.
- `workspace_sync_to_remote` updates the mirror from the remote.
- `ensure_workspace_clone(reset=true)` rebuilds the mirror.

## Behavior notes

- Workspace persistence: the repo mirror survives across tool calls until explicitly deleted or overwritten.
- Request deduplication: the server uses request metadata (session + message) to avoid duplicate tool execution.
- ChatGPT metadata: the server captures safe ChatGPT headers (conversation, assistant, project, org, session, user IDs) for correlation and includes them in request context/logging.
- Cache control: dynamic endpoints are served with `Cache-Control: no-store`; static assets under `/static` are cacheable.
- File caching: GitHub file contents may be cached in-memory to reduce repeated fetches.

### Response shaping (ChatGPT-friendly tool outputs)

The server supports an optional response shaping mode intended for clients that
benefit from consistent envelopes and bounded output size.

Controls (environment variables):

- `GITHUB_MCP_RESPONSE_MODE`
  - `raw` (default): return tool outputs unchanged.
  - `chatgpt`: enable response shaping for ChatGPT-hosted connectors.
  - When unset, some deployments may auto-enable `chatgpt` for requests that
    include ChatGPT connector metadata.

- `GITHUB_MCP_TOOL_RESULT_ENVELOPE` (default: false)
  - When enabled, mapping (dict-like) tool results are normalized to include an
    `ok` boolean and a `status` string (`success`/`warning`/`error`) when missing.

- `GITHUB_MCP_TOOL_RESULT_ENVELOPE_SCALARS` (default: false)
  - When enabled alongside the envelope, scalar results may be wrapped into a
    mapping (`{"ok": true, "status": "success", "result": ...}`).

- `GITHUB_MCP_RESPONSE_MAX_JSON_CHARS` and `GITHUB_MCP_RESPONSE_MAX_TEXT_CHARS`
  - Bounds for truncating unusually large nested JSON/text fields in shaped
    outputs.

Workspace path handling: workspace file tools enforce that requested paths resolve inside the repository root. Relative traversal and absolute paths that point outside the repo are treated as invalid input. File tools also require non-empty paths; deletion helpers require a non-empty `paths` list. Directory deletion requires `allow_recursive=true` for non-empty directories.

## Render tools (operations)

This server includes a minimal Render integration that supports:

- Listing owners/workspaces (`list_render_owners`)
- Listing services (`list_render_services`, optionally by owner)
- Service operations (`create_render_deploy`, `cancel_render_deploy`, `rollback_render_deploy`, `restart_render_service`)
- Deploy inspection (`list_render_deploys`, `get_render_deploy`, `get_render_service`)
- Log reads (`get_render_logs`)

Operational notes:

- Pagination: `limit` is clamped to a safe range (owners/services/deploys: 1..100; logs: 1..1000).
- `create_render_deploy`: provide at most one of `commit_id` or `image_url`.
- `get_render_logs`: `resource_type` is expected to be `service` or `job`. If both `start_time` and `end_time` are provided, start is validated to be <= end. Timestamps are validated as ISO8601 strings (for example `2026-01-14T12:34:56Z`).

Example requests:

Discover owners/workspaces:

```json
{"tool":"list_render_owners","args":{"limit":20}}
```

List services for a specific owner:

```json
{"tool":"list_render_services","args":{"owner_id":"<owner-id>","limit":20}}
```

Trigger a deploy:

```json
{"tool":"create_render_deploy","args":{"service_id":"<service-id>","clear_cache":false,"commit_id":"<sha>"}}
```

Fetch logs for a service:

```json
{"tool":"get_render_logs","args":{"resource_type":"service","resource_id":"<service-id>","start_time":"2026-01-14T12:34:56Z","end_time":"2026-01-14T13:34:56Z","limit":200}}
```

## Deployment (Render.com)

Adaptiv MCP is deployed through Render.com as a web service. Production deployments are managed via Render (build + deploy + environment variables). Local execution supports development and testing.

Render-specific notes:

- Render injects `PORT` automatically; the process binds to `$PORT`.
- Configure GitHub authentication via Render environment variables (for example `GITHUB_TOKEN`).
- `/healthz` reports token detection and baseline health after deploy.

## Configuration

### Minimum required configuration

At least one GitHub authentication token is needed for the server to access the API:

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, or GITHUB_OAUTH_TOKEN

For Render integration, a Render API token is needed for the server to access the Render API:

- RENDER_API_KEY or RENDER_API_TOKEN (first configured token wins; see RENDER_TOKEN_ENV_VARS)

Transport security (trusted hosts)

- ALLOWED_HOSTS (optional) — comma/space-separated list of hostnames that are allowed to use the MCP transport.
  The server also adds hostnames derived from Render-provided env vars (`RENDER_EXTERNAL_HOSTNAME` / `RENDER_EXTERNAL_URL`).
  If neither ALLOWED_HOSTS nor those Render vars are present, host checks are disabled.

### GitHub authentication

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, GITHUB_OAUTH_TOKEN — GitHub API token (first configured is used)
- GITHUB_API_BASE — override GitHub API base URL

### Controller defaults

- GITHUB_MCP_CONTROLLER_REPO — controller repo full_name (owner/repo)
- GITHUB_MCP_CONTROLLER_BRANCH — controller default branch

### Logging (provider logs)

These flags control provider-side logs (for example, Render logs). They leave tool outputs unchanged.

Provider logs are human-facing by default. This server avoids emitting raw JSON blobs in log lines.
Tool calls are logged as compact request/response snapshots (REQ/RES) suitable for Render-style log viewers.
Multi-line structured context blocks are reserved for warnings/errors and visual previews (or when explicitly enabled).

- QUIET_LOGS (default: false) — suppresses most non-error logs.
- HUMAN_LOGS (default: true) — emits scan-friendly tool call log lines with correlation fields.
- LOG_TOOL_PAYLOADS (default: false) — logs full tool input arguments and full tool results (no truncation).
- LOG_GITHUB_HTTP (default: false) — logs outbound GitHub HTTP method/path/status/duration with correlation fields.
- LOG_GITHUB_HTTP_BODIES (default: false) — includes full GitHub response bodies/headers in provider logs.
- LOG_RENDER_HTTP (default: false) — logs outbound Render HTTP method/path/status/duration with correlation fields.
- LOG_RENDER_HTTP_BODIES (default: false) — includes full Render response bodies/headers in provider logs.
- LOG_HTTP_REQUESTS (default: true) — logs inbound HTTP requests to the ASGI server (method/path/status/duration) with request_id.
- LOG_HTTP_BODIES (default: false) — when enabled, logs the POST /messages body (no truncation). This may include sensitive payloads.
- LOG_TOOL_CALL_STARTS (default: true when HUMAN_LOGS=true; else false) — emit a tool_call_started snapshot line (REQ) for each tool invocation.
- LOG_TOOL_CALLS (default: true) — logs tool call snapshot lines to provider logs (REQ/RES). Failures are logged as warnings.
- GITHUB_MCP_LOG_SNAPSHOTS (default: true) — emit a request snapshot (REQ) and a response snapshot (RES) per tool call.
- GITHUB_MCP_LOG_VERBOSE_EXTRAS (default: false) — include deeper diagnostic fields in provider log extras (schema metadata, etc.).
- GITHUB_MCP_LOG_IDS (default: false) — include correlation IDs (call_id) in the REQ/RES message strings.
- LOG_APPEND_EXTRAS (default: true when HUMAN_LOGS=true; else false) — append a YAML-like `extras:` block to provider log lines for warnings/errors and visual previews.
- LOG_EXTRAS_MAX_LINES (default: 200) — max number of lines appended in the `extras:` block.
- LOG_EXTRAS_MAX_CHARS (default: 20000) — max total characters appended in the `extras:` block.

Visual tool previews
~~~~~~~~~~~~~~~~~~~~

When `HUMAN_LOGS` and `LOG_TOOL_CALLS` are enabled, the server can additionally emit user-facing, color-coordinated previews of common tool payloads into provider logs (for example, Render logs). These previews are intended to be scan-friendly and resemble editor-style output.

Key properties:

- Tool outputs returned to clients are unchanged.
- Previews are written to provider logs only.
- File snippets and diffs include line numbers that correspond to the underlying file (or unified diff hunk headers).

Controls:

- GITHUB_MCP_LOG_VISUALS (default: true) — enable/disable visual previews.
- GITHUB_MCP_LOG_COLOR (default: true) — enable/disable ANSI color + syntax highlighting.
- GITHUB_MCP_LOG_STYLE (default: monokai) — Pygments style for syntax highlighting.
- GITHUB_MCP_LOG_READ_SNIPPETS (default: true) — allow previews for read operations (file snippets, search hits, listings).
- GITHUB_MCP_LOG_DIFF_SNIPPETS (default: true) — allow previews for unified diffs (patches and write diffs).

Write diffs (workspace tools)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Workspace write tools can attach a best-effort unified diff to provider logs so that file mutations (replace/edit/patch) are visually reviewable.

- GITHUB_MCP_LOG_WRITE_DIFFS (default: true) — compute and log write diffs (provider logs only).
- GITHUB_MCP_LOG_WRITE_DIFFS_MAX_CHARS (default: 120000) — cap diff size; larger diffs are truncated.
- GITHUB_MCP_LOG_WRITE_DIFFS_MAX_FILE_CHARS (default: 250000) — skip diff generation for very large files.

HTTP exception logging
~~~~~~~~~~~~~~~~~~~~~~

When `LOG_HTTP_REQUESTS` is enabled, unhandled exceptions inside the ASGI request path are logged as `http_exception` with request_id/session_id/message_id and a full stack trace.

### Tests

- GITHUB_MCP_ENABLE_SYNTHETIC_GITHUB (default: false) — when running unit tests (PYTEST_CURRENT_TEST is set),
  enables deterministic synthetic GitHub responses for this repository. Not enabled outside tests.
- GITHUB_REPO_DEFAULTS — optional JSON object of repo defaults (to reduce API calls). Supported shapes:
  - {"owner/repo": {"default_branch": "main"}}
  - {"owner/repo": "main"} (shorthand)

### Tool metadata verbosity

- GITHUB_MCP_COMPACT_METADATA_DEFAULT — default for whether tool listings return compact metadata

### Workspace settings

- MCP_WORKSPACE_BASE_DIR — base directory for persistent workspace clones (defaults to
  `$XDG_CACHE_HOME/mcp-github-workspaces`, then `~/.cache/mcp-github-workspaces`, then the
  system temp dir)
- MCP_WORKSPACE_APPLY_DIFF_TIMEOUT_SECONDS (default: 300) — timeout (seconds) for applying diffs to the workspace clone

### File cache (GitHub content fetches)

- FILE_CACHE_MAX_ENTRIES (default: 0) — max number of cached file entries (0 disables entry-based eviction)
- FILE_CACHE_MAX_BYTES (default: 0) — max total bytes for cached file contents (0 disables byte-based eviction)

### Concurrency and timeouts

- HTTPX_TIMEOUT, HTTPX_MAX_CONNECTIONS, HTTPX_MAX_KEEPALIVE
- MAX_CONCURRENCY, FETCH_FILES_CONCURRENCY

### GitHub rate limiting and search pacing

- GITHUB_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS (default: 1)
- GITHUB_RATE_LIMIT_RETRY_MAX_ATTEMPTS (default: 2)
- GITHUB_RATE_LIMIT_RETRY_MAX_WAIT_SECONDS (default: 30)
- GITHUB_SEARCH_MIN_INTERVAL_SECONDS (default: 2)

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
