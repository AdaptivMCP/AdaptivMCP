# GitHub MCP Server – Complete Function Reference

This reference covers **every function** defined in `main.py`, including private
helpers, MCP-exposed tools, and HTTP routes. Each entry documents purpose,
parameters, returns, error cases, gating behavior, and recommended chaining
patterns so assistants can automate workflows without step-by-step prompts.

## Environment and configuration helpers

### `_env_flag(name: str, default: bool = False) -> bool`
* **Purpose:** Parse environment variables such as `GITHUB_MCP_AUTO_APPROVE`
  into booleans using common truthy strings.
* **Inputs:** `name` (env var key); `default` fallback when unset.
* **Returns:** `True` when the env var is a truthy string, otherwise `False` or
  `default`.
* **Errors:** None (missing variables simply return the default).
* **Chaining:** Used to seed `WRITE_ALLOWED`; no need to call directly.

### `_with_numbered_lines(text: str) -> List[Dict[str, Any]]`
* **Purpose:** Pair each line of a blob with 1-based line numbers for MCP UI
  rendering.
* **Chaining:** Returned inside `get_file_contents` and similar helpers.

### `_get_github_token() -> str`
* **Purpose:** Resolve the PAT from `GITHUB_PAT` or `GITHUB_TOKEN`.
* **Returns:** Token string.
* **Errors:** Raises `GitHubAuthError` when no token is present.
* **Chaining:** Indirectly used by all GitHub requests; ensure env vars are set
  before invoking any tool.

### `_github_client_instance() -> httpx.AsyncClient`
* **Purpose:** Lazily construct a cached GitHub API client with auth headers,
  timeout limits, connection pooling, and optional HTTP/2.
* **Chaining:** Used by `_github_request` and most GitHub tools; do not call
  directly.

### `_external_client_instance() -> httpx.AsyncClient`
* **Purpose:** Cached client for arbitrary HTTP/HTTPS fetches outside GitHub.
* **Chaining:** Called by `fetch_url` and `_load_body_from_content_url`.

### `_github_request(...) -> Dict[str, Any>`
* **Purpose:** Thin wrapper around `httpx` requests against GitHub with shared
  concurrency semaphore, consistent error handling, JSON parsing, and optional
  text responses.
* **Inputs:** HTTP method/path plus optional params, JSON body, headers, and an
  `expect_json` toggle.
* **Returns:** Dict containing `status_code` and `json` or `text`/`headers`.
* **Errors:** Raises `GitHubAPIError` on HTTP ≥400, including message extraction
  from JSON error payloads.
* **Chaining:** Core building block for nearly all GitHub-facing tools.

### `_decode_github_content(full_name, path, ref='main')`
* **Purpose:** Read a file via the GitHub Contents API, decode base64, and
  return text plus metadata.
* **Returns:** Dict with `status`, decoded `text`, `numbered_lines`, `sha`,
  `path`, and `html_url`.
* **Errors:** `GitHubAPIError` for malformed responses or decode failures.
* **Chaining:** Used by `get_file_contents`; pairs well with
  `update_files_and_open_pr` for targeted edits.

### `_get_branch_sha(full_name, ref)` / `_resolve_file_sha(full_name, path, branch)`
* **Purpose:** Resolve branch or file SHAs for commit operations.
* **Returns:** SHA string or `None` when a file is absent (resolve helper).
* **Errors:** `GitHubAPIError` on API failures.
* **Chaining:** Feed SHAs into `_perform_github_commit` or branch creation to
  avoid race conditions.

### `_perform_github_commit(full_name, path, message, body_bytes, branch, sha)`
* **Purpose:** Perform a GitHub Contents API commit for a single file.
* **Inputs:** Base64-encodes `body_bytes`; includes `sha` when updating.
* **Returns:** Raw `_github_request` response dict.
* **Chaining:** Called by commit/PR helpers; not exposed as an MCP tool.

### `_load_body_from_content_url(content_url, *, context)`
* **Purpose:** Load bytes from sandbox paths, absolute paths, or HTTP(S) URLs
  with optional SANDBOX_CONTENT_BASE_URL rewriting.
* **Errors:** `ValueError` for empty URLs; `GitHubAPIError` on read/fetch
  failures with contextual messages.
* **Chaining:** Drives content ingestion for `commit_file_async` and
  `update_files_and_open_pr`; provide `sandbox:/` paths inside ChatGPT to allow
  host rewriting.

### `_run_shell(cmd, cwd=None, timeout_seconds=300)`
* **Purpose:** Execute shell commands with Git identity env vars injected and
  full stdout/stderr passthrough.
* **Returns:** Dict with `exit_code`, `timed_out`, `stdout`, `stderr`, and
  truncation booleans.
* **Chaining:** Backbone for workspace commands, Git operations, and test runs.

### `_clone_repo(full_name, ref='main')`
* **Purpose:** Clone a GitHub repo to a temporary directory using the PAT for
  authentication.
* **Returns:** Path to the temp directory.
* **Errors:** `GitHubAPIError` when clone fails (non-zero git exit).
* **Chaining:** Used by workspace tools (`run_command`, `run_tests`,
  `apply_patch_and_open_pr`). Always paired with `_cleanup_dir` in finally.

### `_cleanup_dir(path)`
* **Purpose:** Best-effort removal of temp directories.
* **Chaining:** Called in `finally` blocks of workspace tools.

### `_apply_patch_to_repo(repo_dir, patch)`
* **Purpose:** Save and apply a unified diff via `git apply --whitespace=nowarn`
  to mirror in-flight workspace changes.
* **Errors:** `GitHubAPIError` for empty patches or git-apply failures.
* **Chaining:** Invoke before running commands/tests to align the clone with
  staged edits.

### `_structured_tool_error(exc, *, context, path=None)`
* **Purpose:** Normalize exceptions into MCP-friendly error payloads containing
  message, context, optional path, and traceback.
* **Chaining:** Returned by tools instead of propagating exceptions so clients
  receive structured failures.

## Write gating and MCP decorator

### `_ensure_write_allowed(context)`
* **Purpose:** Enforce the in-memory write gate controlled by
  `GITHUB_MCP_AUTO_APPROVE` or `authorize_write_actions`.
* **Errors:** Raises `WriteNotAuthorizedError` when writes are disabled.
* **Chaining:** Call at the top of any write-capable routine.

### `mcp_tool(*, write_action=False, **tool_kwargs)`
* **Purpose:** Wrapper over `FastMCP.mcp.tool` to tag tools with `write`
  metadata and mark read actions as `auto_approved` in tool metadata.
* **Behavior:** Preserves any incoming tags/meta, injects `write_action` flags,
  and attaches the generated tool object to `wrapper._mcp_tool` for FastMCP.
* **Chaining:** Use as a decorator when adding new tools to keep approval tags
  consistent.

### `authorize_write_actions(approved: bool = True)`
* **Type:** MCP tool (read-only) toggling write access.
* **Returns:** `{ "write_allowed": bool }` reflecting the new gate state.
* **Chaining:** First call when a session needs to run any write-tagged tool;
  set `approved=false` to re-disable writes mid-session.

## Read-only discovery and repository info tools

### `get_server_config()`
* **Purpose:** Expose runtime limits, gating status, HTTP settings, git identity,
  and sandbox hints.
* **Chaining:** Recommended first call; informs whether `authorize_write_actions`
  is required and surfaces runtime settings for later parsing.

### `get_rate_limit()` / `get_user_login()` / `get_profile()`
* **Purpose:** Inspect token rate limits and authenticated user identity
  (login/profile).
* **Chaining:** Use `get_user_login` to derive owner names when constructing
  `full_name` strings.

### `get_repo(full_name)` / `get_repository(full_name)`
* **Purpose:** Retrieve repository metadata; `get_repository` enforces
  `owner/repo` validation and surfaces topics/default branch/permissions.
* **Chaining:** Call before write operations to confirm permissions and default
  branches.

### `list_repositories(...)`
* **Purpose:** Paginated listing of accessible repositories with optional
  `affiliation` and `visibility` filters.
* **Chaining:** Feed results into subsequent `get_repo` or browse calls.

### `list_repositories_by_installation(installation_id, per_page=30, page=1)`
* **Purpose:** Enumerate repositories visible to a specific GitHub App
  installation for the authenticated user.
* **Chaining:** When an app exposes many repos, pick an `installation_id` from
  `/user/installations` and feed names into `get_repository` or PR tools.

### `list_recent_issues(...)`
* **Purpose:** List recent issues/PRs visible to the user using GitHub's
  combined `/issues` endpoint.
* **Chaining:** Pair with `fetch_issue`/`fetch_issue_comments` for details.

### `fetch_issue(full_name, issue_number)` / `fetch_issue_comments(...)`
* **Purpose:** Retrieve an issue and its comments.
* **Chaining:** Useful before `comment_on_pull_request` or for summarization
  flows.

### `fetch_pr(full_name, pull_number)` / `get_pr_info(...)`
* **Purpose:** Fetch pull request details; `get_pr_info` extracts a concise
  summary (title/state/draft/merged/head/base/user).
* **Chaining:** Combine with `get_pr_diff`, `fetch_pr_patch`, or reactions
  endpoints when auditing PRs.

### `fetch_pr_comments(...)`
* **Purpose:** Pull request review/issue comments listing with pagination.
* **Chaining:** Precursor to sentiment/reaction analysis.

### `get_pr_diff(...)` / `fetch_pr_patch(...)`
* **Purpose:** Retrieve raw diff or patch representations for a PR.
* **Chaining:** Feed into offline analyzers or patch application flows.

### `list_pr_changed_filenames(...)`
* **Purpose:** Enumerate files changed in a PR with GitHub's file metadata.
* **Chaining:** Identify hotspots before fetching specific files.

### `get_commit_combined_status(full_name, ref)`
* **Purpose:** Aggregate status checks for a commit/ref.
* **Chaining:** Validate CI status before merges or deployments.

### Reaction helpers
* `get_issue_comment_reactions(...)`, `get_pr_reactions(...)`,
  `get_pr_review_comment_reactions(...)`
* **Purpose:** Fetch reactions on issues/PRs/review comments using the
  `squirrel-girl` preview header.
* **Chaining:** Augment reports or auto-respond based on popularity signals.

### `list_write_tools()`
* **Purpose:** Enumerate all write-tagged tools with categories and notes so
  assistants can discover capabilities without scanning code.
* **Chaining:** Call when planning automation flows to choose the right
  higher-level primitive (e.g., `update_files_and_open_pr` vs
  `apply_patch_and_open_pr`).

### Repository browsing helpers
* `list_branches(...)`: Paginated branch listing.
* `get_file_contents(full_name, path, ref='main')`: Fetch and decode a single
  file (includes numbered lines for annotations).
* `fetch_files(full_name, paths, ref='main')`: Batch fetch multiple files in
  parallel (bounded by `FETCH_FILES_CONCURRENCY`). Each path is fetched via the
  contents API with `_decode_github_content`; errors are captured per-path in
  the returned `files` mapping so one failing file does not block the rest.
* `list_repository_tree(...)`: Filtered tree listing with recursion, max entry
  limits, and prefix narrowing to avoid huge payloads. Allows excluding blobs
  or trees and raises `ValueError` on non-positive `max_entries`; trims results
  to `max_entries` and sets `truncated` when more entries were available.
* **Chaining:** Combine `list_repository_tree` to discover paths,
  `get_file_contents` to inspect files, and `update_files_and_open_pr` for
  edits.

### GraphQL and external fetch
* `graphql_query(query, variables=None)`: Execute GitHub GraphQL with shared
  auth client; raises on HTTP errors.
* `search(query, search_type='code', per_page=30, page=1, sort=None, order=None)`: REST
  search endpoint wrapper supporting code, repositories, issues, or commits
  with optional sorting parameters.
* `fetch_url(url)`: Generic HTTP GET via the external client with content
  truncation.
* `download_user_content(content_url)`: Fetch sandbox/local/http content as
  base64; decodes UTF-8 text when possible and returns numbered lines for text
  bodies.
* **Chaining:** Use GraphQL for complex queries (e.g., dependency insights);
  `search` to locate files/PRs quickly; `download_user_content` or `fetch_url`
  for ancillary data like changelogs referenced in issues.

## GitHub Actions observability and control

### `list_workflow_runs(...)`
* **Purpose:** List workflow runs with optional `branch`, `status`, and `event`
  filters.
* **Chaining:** Narrow to recent runs before fetching jobs/logs.

### `list_jobs_for_run(full_name, run_id, per_page=100, page=1)`
* **Purpose:** Enumerate jobs within a run.
* **Chaining:** Pair with `get_job_logs` to drill into failing jobs.

### `get_job_logs(full_name, job_id)`
* **Purpose:** Fetch raw job logs without truncation, automatically unzipping
  the archive GitHub returns.
* **Chaining:** Surface concise diagnostics in assistant responses.

### `wait_for_workflow_run(full_name, run_id, timeout_seconds=900, poll_interval_seconds=10)`
* **Purpose:** Poll a workflow run until completion or timeout.
* **Returns:** Status/conclusion and the run payload, plus `timeout=True` flag
  when applicable.
* **Chaining:** Use after dispatching or rerunning workflows to block until
  stable state.

### `trigger_workflow_dispatch(...)`
* **Type:** Write tool requiring gate approval.
* **Purpose:** Fire a `workflow_dispatch` event with optional inputs.
* **Chaining:** Precede with `authorize_write_actions`; often followed by
  `list_workflow_runs` or `wait_for_workflow_run`.

### `trigger_and_wait_for_workflow(...)`
* **Type:** Write tool combining dispatch and wait logic.
* **Behavior:** Triggers the workflow, finds the most recent run on the ref,
  then polls until completion/timeout; returns `run_id` and wait result.
* **Chaining:** One-call automation for requested workflow executions.

## PR and issue management

### `list_pull_requests(full_name, state='open', head=None, base=None, per_page=30, page=1)`
* **Purpose:** Paginated PR listing with optional head/base filters.
* **Chaining:** Feed into review pipelines or merging workflows.

### `merge_pull_request(full_name, number, merge_method='squash', commit_title=None, commit_message=None)`
* **Type:** Write tool; enforces gate.
* **Purpose:** Merge a PR using squash/merge/rebase with optional commit
  metadata.
* **Chaining:** Validate status via `get_commit_combined_status` first; only use
  when explicitly authorized by the repo owner.

### `close_pull_request(full_name, number)`
* **Type:** Write tool to close without merging.
* **Chaining:** Use after confirming intent; no side effects beyond closure.

### `comment_on_pull_request(full_name, number, body)`
* **Type:** Write tool posting an issue comment on the PR thread.
* **Chaining:** Attach summaries, test results, or status updates after other
  tools (e.g., after `run_tests` or `apply_patch_and_open_pr`).

### `compare_refs(full_name, base, head)`
* **Purpose:** Compare two refs (max 100 files) and truncate overly long patch
  chunks to 8000 characters for safety.
* **Chaining:** Run before merges to summarize changes or detect conflicts.

## Branch, commit, and PR creation helpers

### `create_branch(full_name, new_branch, from_ref='main')`
* **Type:** Write tool creating `refs/heads/{new_branch}` from `from_ref` after
  resolving the base SHA.
* **Chaining:** Common first step before commit flows; pair with
  `update_files_and_open_pr` when a specific branch name is required.

### `ensure_branch(full_name, branch, from_ref='main')`
* **Type:** Write tool ensuring a branch exists; creates from `from_ref` on 404.
* **Chaining:** Idempotent guard before committing or pushing.

### `commit_file_async(full_name, path, message, content=None, *, content_url=None, branch='main', sha=None)`
* **Type:** Write tool scheduling a single-file commit via background task.
* **Behavior:** Accepts inline text or external content URL (mutually
  exclusive); auto-resolves `sha` when omitted; logs progress to stdout.
* **Chaining:** Use for small doc/config edits; follow with
  `create_pull_request` or `compare_refs` if needed. Ensure branch exists via
  `ensure_branch` beforehand.

### `update_file_and_open_pr(full_name, path, content, title, base_branch='main', new_branch=None, body=None, message=None, content_url=None, draft=False)`
* **Type:** Write tool for one-file fixes without cloning.
* **Behavior:** Ensures/creates the branch, commits either inline content or
  bytes loaded from `content_url`, then opens a PR. Rejects simultaneous
  `content`/`content_url` inputs.
* **Chaining:** Fastest route for lint/typo fixes that touch a single file;
  returns `branch` and PR payload for follow-up commentary or status checks.

### `create_pull_request(full_name, title, head, base='main', body=None, draft=False)`
* **Type:** Write tool to open a PR.
* **Chaining:** Typically invoked by higher-level helpers; can be called
  directly after branch pushes.

### `update_files_and_open_pr(full_name, title, files, base_branch='main', new_branch=None, body=None, draft=False)`
* **Type:** Write tool bundling multi-file commits and PR creation.
* **Behavior:** Ensures target branch, commits each `files` entry (content or
  content_url) with optional per-file message, then opens a PR.
* **Error handling:** Returns structured errors from content loading or commit
  steps, including the `path` that failed.
* **Chaining:** Ideal for documentation or simple code edits where a patch is
  already materialized.

## Workspace / full-environment operations

### `run_command(full_name, ref='main', command='pytest', timeout_seconds=300, workdir=None, patch=None)`
* **Type:** Write tool (gated) because it clones and can mutate workspace.
* **Behavior:** Clones the repo, optionally applies a unified diff, runs the
  command with Git identity env vars, and returns stdout/stderr/exit code with
  truncation markers. Temp directory is cleaned automatically.
* **Chaining:** Use for lint/test/build commands; provide `patch` to reflect
  current edits before execution. Pair with `authorize_write_actions` first.

### `run_tests(full_name, ref='main', test_command='pytest', timeout_seconds=600, workdir=None, patch=None)`
* **Type:** Write tool wrapping `run_command` with longer default timeout.
* **Chaining:** Preferred entry for test runs; same patch guidance applies.

### `apply_patch_and_open_pr(full_name, base_branch, patch, title, body=None, new_branch=None, run_tests_flag=False, test_command='pytest', test_timeout_seconds=600, draft=False)`
* **Type:** Write tool combining patch application, optional tests, push, and
  PR creation.
* **Behavior:** Creates a working branch, writes and applies the patch, commits
  only when the patch changes files, optionally runs tests, pushes via PAT, and
  opens a PR. Returns branch name, optional test results, PR response, and
  error codes (`empty_patch`, `git_checkout_failed`, `apply_failed`,
  `git_commit_failed`, `tests_failed`, `git_push_failed`, `empty_diff`).
* **Chaining:** Primary single-call flow for proposing code changes when a
  unified diff is available. Combine with
  `get_file_contents`/`list_repository_tree` to build the patch, then
  `comment_on_pull_request` for status updates.

## Webhook-style HTTP routes and lifecycle

### `homepage(request)` (`@mcp.custom_route('/')`)
* **Purpose:** Simple GET endpoint returning a connection hint for MCP clients.
* **Chaining:** Health/informational only.

### `healthz(request)` (`@mcp.custom_route('/healthz')`)
* **Purpose:** Liveness probe returning "OK".

### `_shutdown_clients()`
* **Purpose:** Close cached HTTP clients during FastMCP shutdown events to avoid
  resource leaks.
* **Chaining:** Registered via `app.add_event_handler("shutdown", _shutdown_clients)`;
  not user-invoked.

## Building automation chains

* **Read → analyze → edit → PR:** `get_server_config` → `authorize_write_actions`
  (if needed) → `list_repository_tree`/`get_file_contents` → craft patch →
  `apply_patch_and_open_pr` → `comment_on_pull_request` with results.
* **Doc update from sandbox file:** `authorize_write_actions` → `ensure_branch`
  → `commit_file_async` with `content_url` pointing to `sandbox:/...` →
  `create_pull_request`.
* **CI rerun with wait:** `authorize_write_actions` →
  `trigger_and_wait_for_workflow` → `get_job_logs` for failed jobs →
  `comment_on_pull_request` summarizing outcomes.
* **Test before PR:** `run_tests` (with `patch`) → if clean, use
  `apply_patch_and_open_pr` or `update_files_and_open_pr` to publish changes.

Use these chains as templates; all write steps require `authorize_write_actions`
unless `GITHUB_MCP_AUTO_APPROVE` is preset.
