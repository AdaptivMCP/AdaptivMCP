# chatgpt-mcp-github
Fast GitHub MCP connector optimized for private repositories. The server exposes a set of GitHub-focused tools plus a small number of generic HTTP helpers so assistants can read, write, and automate against GitHub repos with minimal ceremony.

## Configuration
- `GITHUB_PAT` / `GITHUB_TOKEN` (required): Token used for all GitHub requests (needed for private repos).
- `GITHUB_API_BASE` (optional): Override the GitHub REST base URL (defaults to `https://api.github.com`).
- `GITHUB_GRAPHQL_URL` (optional): Override the GraphQL endpoint (defaults to `https://api.github.com/graphql`).
- `GITHUB_MCP_AUTO_APPROVE` (optional): Set to `1` to skip the authorization prompt and auto-approve tools for the session.
- `HTTPX_TIMEOUT`, `HTTPX_MAX_KEEPALIVE`, `HTTPX_MAX_CONNECTIONS` (optional): Tune httpx connection pooling and timeouts.
- `HTTPX_HTTP2` (optional): Set to `1` to enable HTTP/2 if `httpx[http2]` is installed.
- `FETCH_FILES_CONCURRENCY` (optional): Maximum concurrent requests when using `fetch_files` (default `100`).

### Session authorization
Most tools refuse to run until the session is explicitly approved. Call `authorize_github_session` once (or set `GITHUB_MCP_AUTO_APPROVE=1`) before using the other tools.

## Tool reference
All tools return JSON responses. Paths requiring a repository expect the format `owner/repo`.

### General / setup
- `authorize_github_session()`: Mark the current session as trusted so subsequent GitHub tools can run without extra prompts.
- `sanity_check(ctx)`: Lightweight probe to confirm the server is reachable and logging works.

### GitHub REST & GraphQL
- `github_request(method, path, query=None, body=None)`: Low-level REST request against the GitHub API (e.g., `path="/user"`). Uses shared auth headers automatically.
- `github_graphql(query, variables=None)`: Execute a GraphQL query against the configured GraphQL endpoint.
- `github_rate_limit()`: Inspect current REST API rate limits for the token.
- `github_whoami()`: Retrieve the authenticated user associated with the token.

### Repository inspection
- `list_repo_tree(repository_full_name, ref="main", recursive=True)`: Fetch the raw git tree at a ref via `/git/trees`. When `recursive=True`, GitHub returns nested entries.
- `list_repo_files(repository_full_name, ref="main")`: Flattened list of file paths (blobs only) for the given ref with a `file_count` summary.
- `search_code(repository_full_name, query, per_page=50, page=1)`: Run GitHub code search scoped to a single repo; the `repo:` qualifier is added automatically.

### File access helpers
- `fetch_file(repository_full_name, path, ref="main", encoding="utf-8", raw=True, timeout=None)`: Fetch a single file. When `raw=True`, returns raw `text`/`bytes` quickly; when `raw=False`, decodes the `/contents` payload into `decoded` text or bytes along with size metadata.
- `fetch_files(repository_full_name, paths, ref="main", encoding="utf-8", raw=True, concurrency=FETCH_FILES_CONCURRENCY, timeout=None)`: Concurrently fetch multiple files. Returns a mapping of path -> `{ ok: bool, result|error }` and will honor the provided concurrency cap.

### Repository write operations
- `commit_file(repository_full_name, path, content, message, branch="main", encoding="utf-8", sha=None, committer_name=None, committer_email=None)`: Create or update a file via the Contents API. If `sha` is omitted, the current file sha is retrieved automatically to allow updates.
- `commit_files_git(repository_full_name, files, message, branch="main", encoding="utf-8", force=False, use_base64=True)`: Commit one or more files using the Git Data API (blobs/trees/commits). This is optimized for large modules because it bypasses Contents API size limits.
- `create_branch(repository_full_name, new_branch, from_ref="main")`: Create a new branch from the specified base ref (uses `/git/refs`).
- `create_pull_request(repository_full_name, title, head, base="main", body=None, draft=False)`: Open a pull request from `head` to `base`.

### External fetch helper
- `fetch_url(url, method="GET", headers=None, body=None, timeout=None)`: Generic HTTP request for non-GitHub URLs (follows redirects). Useful for quick web checks from within the same MCP session.
