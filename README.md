# chatgpt-mcp-github
Fast GitHub MCP connector optimized for private repositories. The server exposes a set of GitHub-focused tools plus a small number of generic HTTP helpers so assistants can read, write, and automate against GitHub repos with minimal ceremony. It also serves an SSE endpoint on `/sse` (with a health message on `/`) for MCP-compatible clients.

## Configuration
- `GITHUB_PAT` / `GITHUB_TOKEN` (required): Token used for all GitHub requests (needed for private repos).
- `GITHUB_API_BASE` (optional): Override the GitHub REST base URL (defaults to `https://api.github.com`).
- `GITHUB_GRAPHQL_URL` (optional): Override the GraphQL endpoint (defaults to `https://api.github.com/graphql`).
- `GITHUB_MCP_AUTO_APPROVE` (optional): Set to `1` to auto-approve write tools (commits, branches, PRs) for the session.
- `HTTPX_TIMEOUT`, `HTTPX_MAX_KEEPALIVE`, `HTTPX_MAX_CONNECTIONS` (optional): Tune httpx connection pooling and timeouts.
- `HTTPX_HTTP2` (optional): Set to `1` to enable HTTP/2 if `httpx[http2]` is installed.
- `FETCH_FILES_CONCURRENCY` (optional): Maximum concurrent requests when using `fetch_files` (default `100`).

### Session authorization
Read-only tools do not require approval. Call `authorize_write_actions` once to enable write tools (commit files, create branches, open PRs). Set `GITHUB_MCP_AUTO_APPROVE=1` to skip the prompt entirely in trusted deployments. Tools are annotated with `write_action` metadata so clients can surface read/write intent in their UI.

## Tool reference
All tools return JSON responses. Paths requiring a repository expect the format `owner/repo`.

### General / setup
- `authorize_write_actions(approved=True)`: Mark the current session as trusted so write tools (commits, branches, PRs) run without extra prompts.
- `graphql_query(query, variables=None)`: Execute GraphQL queries against the configured GitHub endpoint.

### GitHub inspection
- `get_rate_limit()`: Inspect current REST API rate limits for the token.
- `get_repository(full_name)`: Retrieve repository metadata (`owner/repo`).
- `list_branches(full_name, per_page=100, page=1)`: List branches for a repository.
- `get_file_contents(full_name, path, ref="main")`: Fetch decoded text and raw metadata for a repository file.
- `fetch_files(full_name, paths, ref="main")`: Fetch multiple files concurrently with decoded content when base64-encoded.

### GitHub Actions visibility
- `list_workflow_runs(full_name, branch=None, status=None, event=None, per_page=20, page=1)`: List recent workflow runs.
- `get_workflow_run(full_name, run_id)`: Get details for a specific run.
- `list_workflow_run_jobs(full_name, run_id, per_page=50, page=1)`: List jobs within a run.
- `get_job_logs(full_name, job_id)`: Retrieve raw logs for a job.

### Repository write operations
- `create_branch(full_name, new_branch, from_ref="main")`: Create a new branch from the specified base ref (uses `/git/refs`).
- `commit_file(full_name, path, message, content=None, content_url=None, branch="main", sha=None)`: Create or update a file. Content can be passed inline or fetched from a remote URL, local path, or `file://` URL via `content_url`.
- `create_pull_request(full_name, title, head, base="main", body=None, draft=False)`: Open a pull request from `head` to `base`.

### External fetch helper
- `fetch_url(url)`: Generic HTTP GET for non-GitHub URLs (follows redirects). Useful for quick web checks from within the same MCP session.
