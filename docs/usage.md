# Adaptiv GitHub MCP server usage

This document describes the current functionality, behavior, and recommended usage
patterns for the GitHub MCP (Model Context Protocol) server.

Deployment note: Adaptiv MCP is deployed **only via Render.com** in production. Local execution (for development) is supported.

## Key concepts

1) Repository clone (persistent)

When you use any workspace-backed tool, the server maintains a persistent git clone of the target repository on the server filesystem. This clone is what workspace tools operate on (editing files, running commands, committing, and pushing).

Important: the persistent clone is not the live GitHub state. It is a local copy that only becomes “live” on GitHub after you push.

2) Server “workspace”

In this project’s terminology, “workspace” refers to the server-side environment where the persistent clone lives and where commands run. You should think of it as: a stable working directory + the repo clone.

Because the workspace holds the clone, the two terms are closely related, but the clone is the source of truth for edits, while GitHub remains the source of truth for the remote state.

3) GitHub API tools vs workspace tools

- Workspace tools: operate on the persistent clone (local filesystem + git).
- GitHub API tools: inspect or mutate GitHub’s remote state (issues, PRs, Actions, contents API, etc.).

## Write gate (auto-approval)

This server supports approval-gated write actions. The environment variable `GITHUB_MCP_WRITE_ALLOWED` controls whether write actions are auto-approved.

- `GITHUB_MCP_WRITE_ALLOWED=true`: write tools are auto-approved.
- `GITHUB_MCP_WRITE_ALLOWED=false`: write tools remain executable, but clients should prompt/confirm before invoking write tools.

Introspection and actions-compat listings expose:

- `write_action`: tool is classified as a write.
- `write_allowed`: tool is executable (approval-gated writes still execute).
- `write_actions_enabled` / `write_auto_approved`: writes are auto-approved.
- `approval_required`: client should prompt before invoking the tool.

## What this server provides

- MCP tool surface for GitHub operations: repositories, issues, PRs, actions, files
- Workspace-backed commands for local edits (via the persistent clone)
- Health diagnostics via /healthz

For a complete tool catalog and schemas, see `Detailed_Tools.md`.

## Runtime endpoints

The ASGI application is exposed in `main.py` as `app`.

- GET /sse — MCP transport endpoint (SSE)
- GET /healthz — JSON health status and controller defaults
- GET /v1/actions and GET /actions — Actions-compatible tool listing
- GET /static/* — static assets (if `assets/` is present)

## Recommended workflows

### Read-only workflows

Use GitHub API read tools for discovery and inspection:

- get_repo_defaults, get_server_config, validate_environment
- list_recent_issues, list_repository_issues, fetch_issue
- fetch_pr, get_pr_info, list_pr_changed_filenames

If REST helpers are blocked by client safety gating, use the GraphQL fallbacks:

- list_open_issues_graphql
- list_workflow_runs_graphql, list_recent_failures_graphql
- get_repo_dashboard_graphql

### Edit workflows (clone-first)

Edits should be done in the persistent clone.

Typical flow:

1. Prepare or reuse the clone
   - Use `ensure_workspace_clone` to create or re-use the persistent clone.
   - Use `workspace_sync_status` to see whether the clone is ahead/behind or has uncommitted changes.

2. Make changes in the clone
   - Edit files using workspace file tools or shell editors.
   - Validate changes using your normal commands (tests, linters, etc.).

3. Commit and push from the clone
   - Use `terminal_command` (or the higher-level git helpers) to run:
     - git add
     - git commit
     - git push

4. Refresh when you need a clean snapshot
   - The local clone does not automatically reflect the live GitHub state unless you fetch/pull or recreate the clone.
   - If you need to ensure the clone exactly matches a branch’s remote state, use `workspace_sync_to_remote`.
   - As a last resort, re-clone with `ensure_workspace_clone(reset=true)`.

### GitHub API usage guidance

Because the clone is not the live GitHub state, use GitHub API tools intentionally:

- Use workspace tools for changes, then push.
- After pushing, use GitHub API tools to confirm live state (PR status, CI, branch contents, etc.).
- If you push and then need the clone to match GitHub exactly (for example, after a merge or force-update), re-sync/re-clone before continuing to work.

## Behavior notes

- Workspace persistence: the persistent clone survives across tool calls until explicitly deleted or overwritten.
- Request deduplication: the server uses request metadata (session + message) to avoid duplicate tool execution.
- ChatGPT metadata: the server captures safe ChatGPT headers (conversation, assistant, project, org, session, user IDs) for correlation and includes them in request context/logging.
- File caching: GitHub file contents may be cached in-memory to reduce repeated fetches.
- Workspace file and listing tools reject paths that resolve outside the repository root.
- Workspace search is a bounded, non-shell search:
  - `search_workspace.query` is always treated as a literal substring match (regex is accepted for compatibility but not enforced).
  - `max_results` and `max_file_bytes` are accepted for compatibility/observability but are not enforced as output limits.

## Deployment (Render.com only)

Adaptiv MCP is deployed exclusively through Render.com as a web service. Production deployments should be managed via Render (build + deploy + environment variables). Local execution is supported for development and testing only.

Render-specific notes:

- Render injects `PORT` automatically; ensure the process binds to `$PORT`.
- Configure GitHub authentication via Render environment variables (for example `GITHUB_TOKEN`).
- Use `/healthz` after deploy to verify token detection and baseline health.

## Configuration

### Minimum required configuration

At minimum, set one GitHub authentication token so the server can access the API:

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, or GITHUB_OAUTH_TOKEN

### GitHub authentication

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, GITHUB_OAUTH_TOKEN — GitHub API token (first configured is used)
- GITHUB_API_BASE — override GitHub API base URL

### Controller defaults

- GITHUB_MCP_CONTROLLER_REPO — controller repo full_name (owner/repo)
- GITHUB_MCP_CONTROLLER_BRANCH — controller default branch
- GITHUB_REPO_DEFAULTS — optional JSON object of repo defaults (to reduce API calls). Supported shapes:
  - {"owner/repo": {"default_branch": "main"}}
  - {"owner/repo": "main"} (shorthand)

### Write gate (auto-approval)

- GITHUB_MCP_WRITE_ALLOWED — when true, write tools are auto-approved; when false, clients should prompt

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

### Host filtering

- ALLOWED_HOSTS — optional comma-separated list of allowed hosts (used for request host validation)

### Sandbox/content rewrite (optional)

- SANDBOX_CONTENT_BASE_URL — optional base URL used when rewriting content paths for sandboxed environments

### Logging

- LOG_LEVEL
- LOG_FORMAT

## Local development

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Once running, point your MCP client at /sse and verify /healthz is healthy.

## Troubleshooting tips

- Use `validate_environment` to confirm GitHub tokens and defaults.
