# Adaptiv GitHub MCP server usage

This document describes the current functionality, behavior, and recommended usage
patterns for the self-hosted GitHub MCP (Model Context Protocol) server.

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

## What this server provides

- MCP tool surface for GitHub operations: repositories, issues, PRs, actions, files
- Workspace-backed commands for local edits (via the persistent clone)
- Observability helpers: recent tool events, server logs, and health diagnostics
- Render.com integration (optional): fetch service logs and metrics when configured

For a complete tool catalog, see `Detailed_Tools.md`.

## Runtime endpoints

The ASGI application is exposed in `main.py` as `app`.

- GET /sse — MCP transport endpoint (SSE)
- GET /healthz — JSON health status, controller defaults, and metrics snapshot
- GET /v1/actions and GET /actions — Actions-compatible tool listing
- GET /static/* — static assets (if `assets/` is present)

## Recommended workflows

### Read-only workflows

Use GitHub API read tools for discovery and inspection:

- get_repo_defaults, get_server_config, validate_environment
- list_recent_issues, list_repository_issues, fetch_issue
- fetch_pr, get_pr_info, list_pr_changed_filenames

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

### GitHub API usage guidance

Because the clone is not the live GitHub state, use GitHub API tools intentionally:

- Use workspace tools for changes, then push.
- After pushing, use GitHub API tools to confirm live state (PR status, CI, branch contents, etc.).
- If you push and then need the clone to match GitHub exactly (for example, after a merge or force-update), re-clone/refresh the clone before continuing to work.

## Behavior notes

- Workspace persistence: the persistent clone survives across tool calls until explicitly deleted or overwritten.
- Request deduplication: the server uses request metadata (session + message) to avoid duplicate tool execution.
- File caching: GitHub file contents may be cached in-memory to reduce repeated fetches.

## Configuration

### GitHub authentication

- GITHUB_PAT, GITHUB_TOKEN, GH_TOKEN, GITHUB_OAUTH_TOKEN — GitHub API token (first configured is used)
- GITHUB_API_BASE — override GitHub API base URL

### Render observability (optional)

- RENDER_API_KEY — Render API authentication
- RENDER_SERVICE_ID — default Render resource
- RENDER_OWNER_ID — default owner identifier

### Workspace settings

- MCP_WORKSPACE_BASE_DIR — base directory for persistent workspace clones

### Concurrency and timeouts

- HTTPX_TIMEOUT, HTTPX_MAX_CONNECTIONS, HTTPX_MAX_KEEPALIVE
- MAX_CONCURRENCY, FETCH_FILES_CONCURRENCY

### Output limits

- TOOL_STDOUT_MAX_CHARS, TOOL_STDERR_MAX_CHARS, TOOL_STDIO_COMBINED_MAX_CHARS
- WORKSPACE_SHELL_RESULT_MAX_CHARS, WORKSPACE_COMMIT_FILE_LIST_MAX_ITEMS
- WRITE_DIFF_LOG_MAX_LINES, WRITE_DIFF_LOG_MAX_CHARS
- RUN_COMMAND_MAX_CHARS
- GITHUB_ERROR_TEXT_MAX_CHARS
- MCP_TOOL_ARGS_PREVIEW_MAX_CHARS

### Tool registry controls

- MCP_TOOL_DENYLIST — comma-separated tool names to disable (set to none to allow all)

### Logging

- LOG_LEVEL, LOG_FORMAT, LOG_STYLE

## Local development

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Once running, point your MCP client at /sse and verify /healthz is healthy.

## Troubleshooting tips

- Use validate_environment to confirm GitHub tokens and defaults.
- Use get_recent_server_logs or get_recent_tool_events when provider logs are unavailable.
- For Render deployments, use list_render_logs and get_render_metrics after configuring RENDER_API_KEY.
