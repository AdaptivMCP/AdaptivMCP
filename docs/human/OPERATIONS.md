# Operations runbook

This document covers operating the Adaptiv Controller GitHub MCP server in production (Render) and in self-hosted environments.

## 1) What “healthy” looks like

A healthy deployment has:

- `/healthz` responds quickly.
- `validate_environment` succeeds.
- Tools appear consistently for assistants (`list_all_actions`).
- Render logs are readable and user-facing (CHAT/INFO/DETAILED behave as expected).
- GitHub Actions is green for the main branch (or the deployed branch).

## 2) Required configuration

### GitHub auth (required)

You must provide at least one of:

- `GITHUB_PAT`
- `GITHUB_TOKEN`

If both are set, the server prefers `GITHUB_PAT`.

### Render integration (optional)

If you want Render observability tools, set:

- `RENDER_API_KEY` (required for Render API calls)
- `RENDER_SERVICE_ID` (strongly recommended; used to resolve defaults)
- `RENDER_OWNER_ID` (required by Render `/logs`; avoids extra lookups)

See `.env.example` for the complete list.

### Logging controls

- `LOG_LEVEL`: supports standard levels plus `CHAT` and `DETAILED`.
- `LOG_STYLE`: `plain` or `color`.
- `UVICORN_ACCESS_LOG`: enable/disable GET/POST access log lines.

### Output safety controls

Several env vars exist to prevent hangs and huge payloads (especially on small instances):

- `TOOL_STDOUT_MAX_CHARS`, `TOOL_STDERR_MAX_CHARS`, `TOOL_STDIO_COMBINED_MAX_CHARS`
- `GET_FILE_WITH_LINE_NUMBERS_DEFAULT_MAX_LINES`, `GET_FILE_WITH_LINE_NUMBERS_DEFAULT_MAX_CHARS`
- `WRITE_DIFF_LOG_MAX_LINES`, `WRITE_DIFF_LOG_MAX_CHARS`

## 3) Render deployment specifics

### CI → deploy chain

For the controller repo running on Render:

1. A push lands on `main`.
2. GitHub Actions runs.
3. If CI is green, Render performs a deploy.
4. The service typically takes a few minutes to become fully ready.

### Verifying the running revision

Preferred verification loop:

- Run `validate_environment` (it reports controller revision metadata).
- Poll `list_render_logs(limit=100, direction='backward')` every ~60 seconds until you see:
  - boot sequence
  - steady state
  - expected tool-call logs

### Finding `RENDER_OWNER_ID`

Render’s `/logs` endpoint requires an `ownerId`.

If you don’t know it, use the Render API directly (or set `RENDER_OWNER_ID` once and keep it stable).

## 4) Render log UX guidelines

Render logs are intentionally user-facing.

- `CHAT`: what the assistant would say in chat (“I’m going to run the lint suite next…”)
- `INFO`: progress updates and decisions
- `DETAILED`: tool args, diagnostics, and bounded diffs

Avoid exposing internal ids (caller ids, request ids, opaque routing ids) in `CHAT`/`INFO`.

If you see “random characters” in logs during terminal runs, the root cause is usually control sequences (ANSI escapes) or terminal cursor control output from interactive commands.

Operational mitigations:

- Prefer non-interactive commands and disable pagers (`--no-pager`, `PAGER=cat`, `GIT_PAGER=cat`).
- Prefer `LOG_STYLE=plain` if the client UI is sensitive.
- Keep `terminal_command` output bounded (use `head`, `tail`, `-n`, explicit ranges).

## 5) SSE and edge caching

If you host behind a proxy/CDN (including Render’s edge), ensure SSE endpoints are not cached.

- `/sse` and `/messages` must send `Cache-Control: no-store`.
- If clients report missing events or stuck sessions, check for caching behavior first.

## 6) Tool availability (assistants vs humans)

Tools are registered server-side and exposed via MCP.

To confirm the tool surface is available to assistants:

- `list_all_actions(include_parameters=true)`
- `get_server_config`

If a human says “the tool list didn’t update”, it’s usually a client-side connector refresh:

- refresh the connector list in the host UI (Apps/Connections)
- then re-run `list_all_actions`

## 7) Incident checklist

If something is broken:

1. `validate_environment`
2. Check `/healthz`
3. `list_render_logs(limit=200, direction='backward')` (if on Render)
4. `get_recent_tool_events(limit=50, include_success=true)`
5. Inspect latest CI status (GitHub Actions)

