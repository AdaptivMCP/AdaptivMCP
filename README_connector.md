# GitHub MCP connector quickstart

This server exposes GitHub management tools over MCP for ChatGPT connectors. It
authenticates with a server-side personal access token (``GITHUB_PAT`` /
``GITHUB_TOKEN``) and never forwards credentials to the client.

## Endpoint
Use the SSE endpoint in your connector configuration:

```
https://github-mcp-chatgpt.onrender.com/sse
```

If you visit the base domain directly (``https://github-mcp-chatgpt.onrender.com/``),
the server now responds with a plain-text banner pointing you to ``/sse`` and
``/healthz`` instead of a generic 404.

## Write gating
Write tools are gated to avoid accidental changes.

- Environment default: ``GITHUB_MCP_AUTO_APPROVE=0`` leaves writes disabled at
  startup. Set it to truthy strings like ``1``, ``true``, ``yes``, or ``on`` to
  enable write tools immediately.
- Runtime override via the control tool:

```jsonc
// Tool: authorize_write_actions
{
  "approved": true   // or false
}
```

If writes are disabled, write-tagged tools raise
``WriteNotAuthorizedError`` with context about the requested action.

## Response truncation
Shell outputs and fetched logs are trimmed to keep responses predictable for the
ChatGPT connector UI:

- ``TOOL_STDOUT_MAX_CHARS`` (fixed 12,000) trims stdout text.
- ``TOOL_STDERR_MAX_CHARS`` (env configurable, default 12,000) trims stderr
  text separately.
- ``LOGS_MAX_CHARS`` trims GitHub Actions logs (~16,000 chars).

Adjust ``TOOL_STDERR_MAX_CHARS`` via environment variable if stderr snippets are
being truncated too aggressively.

## Tool catalog
A concise reference for the Actions list inside ChatGPT. All tools inherit the
write gate rules above.

### Control
- **authorize_write_actions(approved: bool = True)** — Toggle write tools on or
  off for the running process.

### Server introspection
- **get_server_config()** — Return non-sensitive connector configuration such as
  write gating, HTTP timeouts, concurrency limits, log truncation, Git identity,
  and whether sandbox content URLs are configured.
- **list_write_tools()** — List write-capable tools, their categories, and
  safety notes to avoid scanning main.py manually.

### Repository inspection / reads
- **get_rate_limit()** — Return the authenticated token's rate-limit document.
- **get_repository(full_name)** — Repository metadata (topics, default branch,
  permissions). ``full_name`` must be ``"owner/repo"``.
- **list_branches(full_name, per_page=100, page=1)** — Enumerate branches using
  GitHub pagination.
- **get_file_contents(full_name, path, ref="main")** — Fetch one file and
  decode base64 to UTF-8 text. Responses include `numbered_lines` to make
  quoting specific lines in patches easier.
- **fetch_files(full_name, paths, ref="main")** — Fetch multiple files
  concurrently; each entry returns decoded content, `numbered_lines`, or an
  error string.
- **graphql_query(query, variables=None)** — Execute a GitHub GraphQL query.
- **fetch_url(url)** — Fetch arbitrary HTTP/HTTPS URLs with content truncation.

### GitHub Actions
- **list_workflow_runs(full_name, branch?, status?, event?, per_page=30,
  page=1)** — List recent workflow runs with filters.
- **get_workflow_run(full_name, run_id)** — Details for a single workflow run.
- **list_workflow_run_jobs(full_name, run_id, per_page=30, page=1)** — Jobs
  inside a workflow run.
- **get_job_logs(full_name, job_id)** — Raw job logs truncated to
  ``LOGS_MAX_CHARS``.
- **wait_for_workflow_run(full_name, run_id, timeout_seconds=900,
  poll_interval_seconds=10)** — Poll until completion or timeout.
- **trigger_workflow_dispatch(full_name, workflow, ref, inputs?)** — Trigger a
  workflow dispatch event (write).
- **trigger_and_wait_for_workflow(full_name, workflow, ref, inputs?,
  timeout_seconds=900, poll_interval_seconds=10)** — Trigger then block until
  the run completes (write).

### PR / issue management
- **list_pull_requests(full_name, state="open", head=None, base=None,
  per_page=30, page=1)** — List PRs with optional head/base filters.
- **compare_refs(full_name, base, head)** — GitHub compare API with patch text
  truncated (~8k chars per file, max 100 files).
- **create_pull_request(full_name, title, head, base="main", body=None,
  draft=False)** — Open a PR respecting the write gate.
- **merge_pull_request(full_name, number, merge_method="squash",
  commit_title=None, commit_message=None)** — Merge a PR via squash/merge/rebase
  (write).
- **close_pull_request(full_name, number)** — Close a PR without merging
  (write).
- **comment_on_pull_request(full_name, number, body)** — Post a PR comment
  (write).

### Branch / commit tools
- **create_branch(full_name, new_branch, from_ref="main")** — Create a branch
  from the given ref (write).
- **ensure_branch(full_name, branch, from_ref="main")** — Idempotently create
  the branch if missing (write).
- **commit_file_async(full_name, path, message, content=None,
  content_url=None, branch="main", sha=None)** — Schedule a single file commit
  in the background; exactly one of ``content``/``content_url`` is required
  (write).
- **update_files_and_open_pr(full_name, title, files[], base_branch="main",
  new_branch?, body?, draft=False)** — Commit multiple files then open a PR
  (write).

### Workspace / full-environment tools
These clone the repository into a temporary directory on the MCP server and
clean up afterward.

- **run_command(full_name, ref="main", command="pytest", timeout_seconds=300,
  workdir=None, patch=None)** — Run an arbitrary command in a temp checkout
  (write gate for safety). If ``patch`` is provided, it is applied with
  ``git apply`` before executing the command so linters/tests run against
  in-flight changes.
- **run_tests(full_name, ref="main", test_command="pytest",
  timeout_seconds=600, workdir=None, patch=None)** — Thin wrapper over
  ``run_command`` with the same patch-support semantics.
- **apply_patch_and_open_pr(full_name, base_branch, patch, title, body=None,
  new_branch=None, run_tests_flag=False, test_command="pytest",
  test_timeout_seconds=600, draft=False)** — Apply a unified diff, optionally
  run tests, push, and open a PR (write). Empty patch bodies return
  ``empty_patch``; patches that apply but stage no changes return
  ``empty_diff`` so no-op commits are avoided.

## Operational hygiene
- Shared httpx clients are closed on shutdown via the FastMCP shutdown handler
  to avoid lingering sockets.
- Shell commands inject ``GIT_AUTHOR_*`` and ``GIT_COMMITTER_*`` env vars from
  configuration, ensuring consistent attribution for auto-generated commits.
