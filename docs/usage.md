# Adaptiv GitHub MCP server usage

This document describes the current functionality, behavior, and recommended usage
patterns for the GitHub MCP (Model Context Protocol) server.

Deployment note: Adaptiv MCP is deployed **only via Render.com** in production. Local execution (for development) is still supported.

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

For a complete tool catalog, see `Detailed_Tools.md`.

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
   - Use render_shell (or terminal_command) to enter the repo’s persistent clone.
   - Run git status / git diff / tests locally against the clone.

2. Make changes in the clone
   - Edit files using workspace file tools or shell editors.
   - Validate changes using your normal commands (tests, linters, etc.).

3. Commit and push from the clone
   - git add
   - git commit
   - git push

4. Re-clone or refresh when you need a clean snapshot
   - The local clone does not automatically reflect the live GitHub state unless you fetch/pull or recreate the clone.
   - If you need to ensure the clone exactly matches a branch’s remote state, re-clone the repo/ref (or delete and re-create the workspace clone).
   - Use `workspace_sync_status` to see ahead/behind and uncommitted changes, then `workspace_sync_to_remote` to hard-reset the clone to the remote branch when needed.

### GitHub API usage guidance

Because the clone is not the live GitHub state, use GitHub API tools intentionally:

- Use workspace tools for changes, then push.
- After pushing, use GitHub API tools to confirm live state (PR status, CI, branch contents, etc.).
- If you push and then need the clone to match GitHub exactly (for example, after a merge or force-update), re-clone/refresh the clone before continuing to work.

## Behavior notes

- Workspace persistence: the persistent clone survives across tool calls until explicitly deleted or overwritten.
- Request deduplication: the server uses request metadata (session + message) to avoid duplicate tool execution.
- ChatGPT metadata: the server captures safe ChatGPT headers (conversation, assistant, project, org, session, user IDs) for correlation and includes them in request context/logging.
- File caching: GitHub file contents may be cached in-memory to reduce repeated fetches.
- Workspace file and listing tools reject paths that resolve outside the repository root.

## Configuration

## Deployment (Render.com only)

Adaptiv MCP is deployed exclusively through Render.com as a web service. Production deployments should be managed via Render (build + deploy + environment variables). Local execution is supported for development and testing only.

Render-specific notes:

- Render injects `PORT` automatically; ensure the process binds to `$PORT`.
- Configure GitHub authentication via Render environment variables (for example `GITHUB_TOKEN`).
- Use `/healthz` after deploy to verify token detection and baseline health.

### Minimum required configuration

At minimum, set one GitHub authentication token so the server can access the API:

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, or GITHUB_OAUTH_TOKEN

### GitHub authentication

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, GITHUB_OAUTH_TOKEN — GitHub API token (first configured is used)
- GITHUB_API_BASE — override GitHub API base URL

### Git identity for workspace commits

Workspace-backed commit tools read Git identity from explicit MCP env vars first, then fall back
to GitHub App metadata, and finally to placeholders. Configure the explicit variables to ensure
commits are attributed correctly:

- GITHUB_MCP_GIT_AUTHOR_NAME
- GITHUB_MCP_GIT_AUTHOR_EMAIL
- GITHUB_MCP_GIT_COMMITTER_NAME
- GITHUB_MCP_GIT_COMMITTER_EMAIL

Optional GitHub App metadata used when explicit values are not provided:

- GITHUB_APP_NAME (used for the name)
- GITHUB_APP_SLUG or GITHUB_APP_ID (used to build a bot login and noreply email)

Example:

```bash
export GITHUB_MCP_GIT_AUTHOR_NAME="Octo Bot"
export GITHUB_MCP_GIT_AUTHOR_EMAIL="octo-bot[bot]@users.noreply.github.com"
export GITHUB_MCP_GIT_COMMITTER_NAME="Octo Bot"
export GITHUB_MCP_GIT_COMMITTER_EMAIL="octo-bot[bot]@users.noreply.github.com"
```

### Workspace settings

- MCP_WORKSPACE_BASE_DIR — base directory for persistent workspace clones

### Concurrency and timeouts

- HTTPX_TIMEOUT, HTTPX_MAX_CONNECTIONS, HTTPX_MAX_KEEPALIVE
- MAX_CONCURRENCY, FETCH_FILES_CONCURRENCY

### Output limits

- WRITE_DIFF_LOG_MAX_LINES

### Logging

- LOG_LEVEL, LOG_FORMAT, LOG_STYLE

## Local development

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Once running, point your MCP client at /sse and verify /healthz is healthy.

## Troubleshooting tips

- Use validate_environment to confirm GitHub tokens and defaults.
