# chatgpt-mcp-github

GitHub MCP server optimized for **private repositories**.

It exposes a focused set of GitHub tools (read + write) plus a small generic HTTP helper so assistants can read, write, and automate against GitHub repos with minimal setup. The server is implemented with `FastMCP`, wrapped in a Starlette app, and served by `uvicorn`.

The MCP endpoint is exposed via **Server-Sent Events (SSE)** on `/sse`, with a simple health message on `/`. This is what your MCP client (e.g. ChatGPT) connects to.

---

## Features

### Read tools

- Inspect GitHub rate limits.
- Read repository metadata and branches.
- Fetch individual files or **batch fetch** many files with decoded content.
- Run arbitrary GraphQL queries against the GitHub API.
- Inspect GitHub Actions runs, jobs, and logs.

### Write tools (opt-in)

- Create branches from an existing ref.
- Commit or update files (content inline or fetched from a URL/path).
- Open pull requests.

Write tools are tagged with `write_action` metadata so MCP clients can clearly show that they mutate state. A helper tool (`authorize_write_actions`) lets you explicitly enable write actions for the current MCP session.

---

## Architecture

- `main.py` defines a `FastMCP` server named **"GitHub Fast MCP"**.
- Tools are registered via a small `mcp_tool` decorator that:
  - Calls `mcp.tool(...)`.
  - Attaches `write_action` metadata for both read and write tools.
- GitHub and external HTTP requests use shared `httpx.AsyncClient` instances with:
  - Connection pooling and configurable concurrency.
  - Optional HTTP/2.
- The FastMCP SSE ASGI app is wrapped in a Starlette app that:
  - Serves `GET /` with a simple banner.
  - Serves `GET /healthz` for health checks.
  - Forwards `/sse` and MCP message paths through a small ASGI wrapper that normalizes the scope so FastMCP always sees the expected paths.
- `uvicorn` is used as the ASGI server.

---

## Configuration

At minimum you must provide a GitHub token with access to the repos you want to work with.

### Required

- `GITHUB_PAT` **or** `GITHUB_TOKEN`  
  GitHub PAT used for all GitHub API calls.  
  For private repos, give it at least the `repo` scope.  
  Add `workflow` if you want to interact with Actions workflows.

### Optional

- `GITHUB_API_BASE` (default `https://api.github.com`)
- `GITHUB_GRAPHQL_URL` (default `https://api.github.com/graphql`)
- `GITHUB_MCP_AUTO_APPROVE` (default `0`)  
  Set to `1` to auto-approve write tools for the session.
- `HTTPX_TIMEOUT` (default `120`) – HTTP timeout in seconds.
- `HTTPX_MAX_KEEPALIVE` (default `100`) – max keep-alive connections.
- `HTTPX_MAX_CONNECTIONS` (default `200`) – max total connections.
- `HTTPX_HTTP2` (default `0`) – set to `1` to enable HTTP/2 (requires `httpx[http2]`).
- `FETCH_FILES_CONCURRENCY` (default `100`) – max concurrent requests in `fetch_files`.

---

## Running locally

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set environment variables

```bash
export GITHUB_PAT=ghp_your_token_here
# or
export GITHUB_TOKEN=ghp_your_token_here
```

Optional tuning variables are listed in the Configuration section above.

### 3. Start the server

The Starlette app is exported as `app` from `main.py`:

```bash
# PORT defaults to 10000 when not set
export PORT=10000
uvicorn main:app --host 0.0.0.0 --port $PORT
```

You should see logs similar to:

```text
Uvicorn running on http://0.0.0.0:10000
```

### 4. Quick health checks

```bash
curl http://localhost:10000/
curl http://localhost:10000/healthz
```

### 5. Test the MCP SSE endpoint

```bash
# Should keep the connection open without 404/405
curl -N http://localhost:10000/sse
```

---

## Deploying on Render

This repo is designed to run as a **Render Web Service**.

### 1. Create the service

1. Create a new **Web Service** in Render.
2. Point it at this GitHub repo and branch (`main` by default).
3. Use the Python runtime.

### 2. Commands

- **Build Command**

  ```text
  pip install -r requirements.txt
  ```

- **Start Command**

  ```text
  uvicorn main:app --host 0.0.0.0 --port $PORT
  ```

Render will inject `PORT` (usually `10000`). The `__main__` block in `main.py` also respects `PORT` if you run the file directly.

### 3. Environment variables

In **Environment → Environment Variables**, set:

- `GITHUB_PAT` (or `GITHUB_TOKEN`) – GitHub PAT with `repo` scope (and `workflow` if you need Actions).
- Any optional variables like `GITHUB_MCP_AUTO_APPROVE`, `FETCH_FILES_CONCURRENCY`, etc.

### 4. Verify deployment

After deploy, your service will be available at:

```text
https://<your-service-name>.onrender.com
```

Check:

```bash
curl https://<your-service-name>.onrender.com/
curl https://<your-service-name>.onrender.com/healthz
curl -N https://<your-service-name>.onrender.com/sse
```

You should **not** see `405 Method Not Allowed` on `POST /sse` in the Render logs.

---

## Using with ChatGPT (MCP connector)

Configure a custom MCP connector in ChatGPT (or another MCP client):

- **URL**:  
  `https://<your-service-name>.onrender.com/sse`
- **Authorization**:  
  None for the MCP transport itself.  
  GitHub access is handled entirely server-side by `GITHUB_PAT` / `GITHUB_TOKEN`.

Once connected, the client should list tools like:

- `authorize_write_actions`
- `get_rate_limit`
- `get_repository`
- `list_branches`
- `get_file_contents`
- `fetch_files`
- `graphql_query`
- `list_workflow_runs`
- `get_workflow_run`
- `list_workflow_run_jobs`
- `get_job_logs`
- `create_branch`
- `commit_file`
- `create_pull_request`
- `fetch_url`

If you plan to let the assistant write to repos, either:

- Call `authorize_write_actions(approved=True)` once per MCP session, or
- Set `GITHUB_MCP_AUTO_APPROVE=1` in the environment for a fully trusted deployment.

---

## Tool reference

All tools return JSON. Any parameter named `full_name` expects `owner/repo`.

### General / setup

- `authorize_write_actions(approved=True)`  
  Enable or disable write tools for the current MCP session.

- `graphql_query(query, variables=None)`  
  Execute a GraphQL query against `GITHUB_GRAPHQL_URL`.

### GitHub inspection

- `get_rate_limit()`  
  View current REST API rate limits.

- `get_repository(full_name)`  
  Get repository metadata.

- `list_branches(full_name, per_page=100, page=1)`  
  List branches.

- `get_file_contents(full_name, path="README.md", ref="main")`  
  Fetch a single file; returns a `decoded` text field plus the raw GitHub API payload.

- `fetch_files(full_name, paths, ref="main")`  
  Fetch multiple files concurrently; each entry includes decoded content if the file was base64-encoded.

### GitHub Actions visibility

- `list_workflow_runs(full_name, branch=None, status=None, event=None, per_page=20, page=1)`
- `get_workflow_run(full_name, run_id)`
- `list_workflow_run_jobs(full_name, run_id, per_page=50, page=1)`
- `get_job_logs(full_name, job_id)`

### Repository write operations

These are marked with `write_action=True` and require `authorize_write_actions` (or `GITHUB_MCP_AUTO_APPROVE=1`).

- `create_branch(full_name, new_branch, from_ref="main")`  
  Create a new branch from the specified base ref.

- `commit_file(full_name, path, message, content=None, content_url=None, branch="main", sha=None)`  
  Create or update a file.  
  - `content`: inline text.  
  - `content_url`: HTTP(S) URL or `file://` / local path that the server will fetch.  
  - `sha`: pass the existing file SHA to update; omit to create.

- `create_pull_request(full_name, title, head, base="main", body=None, draft=False)`  
  Open a pull request.

### External helper

- `fetch_url(url)`  
  Simple HTTP `GET` for non-GitHub URLs (follows redirects). Useful for diagnostics within the same MCP session.

---

## Troubleshooting

- **MCP client shows 405 on `/sse`**  
  - Ensure the Start Command is `uvicorn main:app --host 0.0.0.0 --port $PORT`.  
  - Confirm `/` and `/healthz` return `200`.  
  - Check logs for `POST /sse` and `GET /sse` from the client; status codes should be `2xx`.

- **GitHub requests return 401/403**  
  - Verify `GITHUB_PAT` / `GITHUB_TOKEN` is set and has correct scopes.  
  - Make sure the token is configured in the Render service’s environment, not just locally.

- **Rate-limit or connection issues when batch fetching files**  
  - Lower `FETCH_FILES_CONCURRENCY`.  
  - Reduce the number of files requested per call.
