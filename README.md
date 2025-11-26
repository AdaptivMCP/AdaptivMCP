# chatgpt-mcp-github

GitHub MCP server for private repositories, tuned for fast read and safe write workflows from ChatGPT.

This service runs as a Python web service on Render and exposes a Model Context Protocol (MCP) SSE endpoint at `/sse` for use by ChatGPT or any other MCP client that understands the SSE transport.

## What this server does

From the point of view of an MCP client, this server:

- Reads repository metadata, branches and files (including batch fetch via `fetch_files`).
- Runs GitHub REST and GraphQL requests using a PAT stored server side.
- Inspects GitHub Actions workflow runs, jobs and logs.
- Creates branches, commits files, opens pull requests and can trigger `workflow_dispatch` workflows.
- Provides higher level tools like `update_files_and_open_pr` and `apply_patch_and_open_pr` to safely edit code and open PRs.
- Can clone repos into a temporary workspace and run commands or test suites there.

The deployment is meant for a single trusted user. The GitHub personal access token (PAT) lives only in the server environment; the MCP client never sees it.

## Architecture

- `main.py` defines a FastMCP server named **GitHub Fast MCP**.
- Tools are registered via a small `mcp_tool` decorator that also marks which tools are write actions.
- A Starlette app wraps the FastMCP SSE ASGI app and exposes:
  - `GET /`  simple banner.
  - `GET /healthz`  health check for Render.
  - `GET/POST /sse` and related MCP message endpoints via `mcp.sse_app()`.
- GitHub and external HTTP requests go through shared `httpx.AsyncClient` instances with:
  - Connection pooling controlled by `HTTPX_MAX_CONNECTIONS` and `HTTPX_MAX_KEEPALIVE`.
  - Optional HTTP/2 via `HTTPX_HTTP2`.
  - Tunable timeouts via `HTTPX_TIMEOUT`.

The server trims very large logs, patches and command output to keep responses inside MCP connector limits.

## Environment variables

### Required

- `GITHUB_PAT` or `GITHUB_TOKEN`  GitHub personal access token used for all GitHub API calls. For private repos, give it at least the `repo` scope. Add `workflow` if you want to inspect or trigger Actions workflows.

### Write gating

- `GITHUB_MCP_AUTO_APPROVE` (default `0`)
  - `0`  write tools are disabled until the `authorize_write_actions` tool is called.
  - Truthy strings such as `1`, `true`, `yes`, or `on` enable write tools by default for all MCP sessions.

### HTTP client and concurrency tuning

All of these have sensible defaults and can usually be left alone:

- `HTTPX_TIMEOUT`  HTTP timeout in seconds (default `150`).
- `HTTPX_MAX_CONNECTIONS`  max total pooled connections (default `300`).
- `HTTPX_MAX_KEEPALIVE`  max idle keep alive connections (default `200`).
- `HTTPX_HTTP2`  set to `1` to enable HTTP/2 where available (default `1`).
- `MAX_CONCURRENCY`  general concurrency limit for some tools (default `80`).
- `FETCH_FILES_CONCURRENCY`  overrides concurrency for `fetch_files`; if unset, falls back to `MAX_CONCURRENCY`.
- `TOOL_STDOUT_MAX_CHARS`  max characters of stdout preserved from commands (default `12000`).
- `TOOL_STDERR_MAX_CHARS`  max characters of stderr preserved from commands (default `12000`).

## Running locally

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

2. Export the GitHub token and optional env vars:

```bash
export GITHUB_PAT=ghp_your_token_here
# or
export GITHUB_TOKEN=ghp_your_token_here
export GITHUB_MCP_AUTO_APPROVE=1  # optional
```

3. Start the server:

```bash
export PORT=10000  # or any free port
uvicorn main:app --host 0.0.0.0 --port $PORT
```

4. Quick health checks:

```bash
curl http://localhost:10000/
curl http://localhost:10000/healthz
curl -N http://localhost:10000/sse
```

## Deploying on Render

1. Create a Web Service pointing at this repo (branch `main`).
2. Use the Python runtime.
3. Configure commands:

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
uvicorn main:app --host 0.0.0.0 --port $PORT
```

4. In the Environment tab, configure at least:

- `GITHUB_PAT` or `GITHUB_TOKEN` with `repo` and optionally `workflow` scopes.
- Optional tuning variables such as `FETCH_FILES_CONCURRENCY`.

5. After deploy, verify:

```bash
curl https://<service>.onrender.com/
curl https://<service>.onrender.com/healthz
curl -N https://<service>.onrender.com/sse
```

## Using with ChatGPT (MCP)

Configure a custom MCP connector in ChatGPT:

- URL  `https://<service>.onrender.com/sse`
- Authentication  none at MCP layer; the server reads `GITHUB_PAT` or `GITHUB_TOKEN` from its environment.

If `GITHUB_MCP_AUTO_APPROVE` is `0`, call `authorize_write_actions` with `approved=true` at the start of a session to enable write tools. If you fully trust the server, set `GITHUB_MCP_AUTO_APPROVE=1` instead.

### Assistant quickstart

1. Call `get_server_config` (and `list_write_tools` if you plan to write) to see whether writes are allowed and what limits apply.
2. Use `list_repository_tree` to browse the repository layout. Pass `path_prefix` to focus on a subdirectory when the top-level tree is large.
3. Fetch live file contents with `get_file_contents` or `fetch_files` so you have numbered lines for planning diffs.
4. Build small, targeted patches and apply them with `apply_patch_and_open_pr`; keep tests on for code changes.
5. Report results, including any test output or truncation notices, back to the user.

Once connected, the client should expose tools such as:

- `authorize_write_actions`
- `get_server_config`, `list_write_tools`
- `get_rate_limit`, `get_repository`, `list_branches`, `list_repository_tree`
- `get_file_contents`, `fetch_files` (responses include `numbered_lines` for
  easy referencing)
- `graphql_query`, `fetch_url`
- GitHub Actions tools  `list_workflow_runs`, `get_workflow_run`, `list_workflow_run_jobs`, `get_job_logs`, `wait_for_workflow_run`, `trigger_workflow_dispatch`, `trigger_and_wait_for_workflow`
- PR tools  `list_pull_requests`, `comment_on_pull_request`, `merge_pull_request`, `close_pull_request`, `compare_refs`
- Branch and commit tools  `create_branch`, `ensure_branch`, `commit_file_async`, `create_pull_request`, `update_files_and_open_pr`
- Workspace tools  `run_command`, `run_tests`, `apply_patch_and_open_pr`

## Troubleshooting

- If the MCP client reports errors talking to `/sse`, check Render logs for requests to `/sse` and confirm the Start Command uses `main:app`.
- If GitHub calls fail with 401 or 403, verify the PAT value and scopes in the Render Environment tab.
- If `fetch_files` or other tools hit timeouts, lower `FETCH_FILES_CONCURRENCY` or reduce the number of files requested per call.
- Large logs and patches are truncated on purpose to keep responses safe for MCP transports.
