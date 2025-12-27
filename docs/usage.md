# Adaptiv GitHub MCP server usage

This document describes the current functionality, behavior, and correct usage
patterns for the self-hosted GitHub MCP (Model Context Protocol) server.

## What this server provides

- **MCP tool surface for GitHub**: read/write GitHub operations (repositories,
  issues, PRs, actions, files), plus workspace-backed commands for local edits.
- **Observability helpers**: in-memory recent tool events, server logs, and
  health diagnostics.
- **Render.com integration** (optional): fetch service logs and metrics when a
  Render API key is configured.

For a complete tool catalog, see
[`Detailed_Tools.md`](../Detailed_Tools.md).

## Runtime endpoints

The ASGI application is exposed in `main.py` as `app`.

- `GET /sse` — MCP transport endpoint (SSE).
- `GET /healthz` — JSON health status, controller defaults, and metrics snapshot.
- `GET /v1/actions` and `GET /actions` — OpenAI Actions-compatible tool listing.
- `GET /static/*` — static assets (if `assets/` is present).

## Usage patterns

### Read-only workflows

Use read-only tools for discovery and inspection:

- `get_repo_defaults`, `get_server_config`, `validate_environment`
- `get_file_contents`, `fetch_files`, `list_repository_tree`
- `list_recent_issues`, `list_repository_issues`, `fetch_issue`
- `fetch_pr`, `get_pr_info`, `list_pr_changed_filenames`

### Workspace-based workflows (recommended for edits)

Workspace tools clone a repo into a persistent directory, allowing edits and
commands to be run locally before pushing changes back to GitHub.

Typical flow:

1. `ensure_workspace_clone` or `render_shell` to prepare the workspace.
2. Edit with `set_workspace_file_contents` or run scripts via `run_command`.
3. Inspect changes with `get_workspace_changes_summary`.
4. Commit and push with `commit_workspace` or `commit_workspace_files`.

### Direct GitHub API file edits

For small changes, you can use GitHub contents APIs via MCP tools:

- `create_file`, `apply_text_update_and_commit`, `move_file`, `delete_file`
- `update_file_from_workspace` to push a workspace file back to GitHub

### Write metadata

Write-capable tools are marked as **remote mutations** in tool metadata. The
current `WRITE_ALLOWED` state is exposed for clients that want to display
read/write status.

## Behavior and safety constraints

- **Request deduplication**: the server uses request metadata (session ID +
  message ID) to avoid duplicate tool execution when upstream retries occur.
- **File caching**: GitHub file contents are cached in-memory to reduce repeated
  fetches. Cache size limits are configurable.
- **Streaming safety**: caching headers are disabled for dynamic endpoints to
  protect SSE streams.
- **Workspace persistence**: workspace clones persist between tool calls until
  explicitly deleted or overwritten.

## Configuration

Key environment variables:

### GitHub authentication

- `GITHUB_PAT`, `GITHUB_TOKEN`, `GH_TOKEN`, `GITHUB_OAUTH_TOKEN` — GitHub API token (first configured is used).
- `GITHUB_API_BASE` — override GitHub API base URL.

### Render observability (optional)

- `RENDER_API_KEY` — Render API authentication.
- `RENDER_SERVICE_ID` — default Render resource.
- `RENDER_OWNER_ID` — default owner identifier.

### Workspace settings

- `MCP_WORKSPACE_BASE_DIR` — base directory for persistent workspace clones.

### Concurrency and timeouts

- `HTTPX_TIMEOUT`, `HTTPX_MAX_CONNECTIONS`, `HTTPX_MAX_KEEPALIVE`
- `MAX_CONCURRENCY`, `FETCH_FILES_CONCURRENCY`

### Output limits

- `TOOL_STDOUT_MAX_CHARS`, `TOOL_STDERR_MAX_CHARS`, `TOOL_STDIO_COMBINED_MAX_CHARS`
- `WRITE_DIFF_LOG_MAX_LINES`, `WRITE_DIFF_LOG_MAX_CHARS`
- `RUN_COMMAND_MAX_CHARS`

### Logging

- `LOG_LEVEL`, `LOG_FORMAT`, `LOG_STYLE`

## Local development

Run the server with an ASGI host such as uvicorn:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Once running, point your MCP client at `/sse` and verify `/healthz` is healthy.

## Troubleshooting tips

- Use `validate_environment` to confirm GitHub tokens and defaults.
- Use `get_recent_server_logs` or `get_recent_tool_events` when provider logs
  are unavailable.
- For Render deployments, use `list_render_logs` and `get_render_metrics` after
  configuring `RENDER_API_KEY`.
