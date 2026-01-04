# Detailed MCP tools reference

This document is the authoritative reference for the Adaptiv GitHub MCP server tool surface. Each tool below is documented with purpose, inputs, outputs, and an example invocation.

If you are looking for higher-level workflows ("how do I make a change and open a PR?"), see `docs/usage.md`.

## Conventions used in this document

- "Tool" means an MCP-exposed function callable by an MCP client.
- Many tools require `full_name`, which is the GitHub repository in `owner/repo` format (example: `Proofgate-Revocations/chatgpt-mcp-github`).
- Some tools accept a git **ref** (`ref`) and others accept a git **branch** (`branch`).
  - `ref` is a git reference string (branch name, tag name, or SHA).
  - `branch` is expected to be a branch name.
- Pagination is usually `per_page` + `page` (1-indexed).
- Timestamps (when present) are usually ISO-8601 strings.

## What Adaptiv MCP responses look like

Adaptiv MCP tools return structured JSON. Most successful calls return an object with a top-level `result` field plus optional metadata used by the controller/UI.

Common fields you may see:

- `result`: Tool-specific payload (the "real" output).
- `summary`: A compact, UI-friendly summary (title + optional bullets/next steps).
- `user_message`: A short human-readable status message.
- `controller_log`: Debug/trace breadcrumbs (may be empty).

Some failures (or safety-gated runs) may return an error-shaped payload instead of `result`.

### Example: successful `list_tools`

```json
{
  "result": {
    "write_actions_enabled": true,
    "tools": [
      {
        "name": "get_repository",
        "write_action": false,
        "write_enabled": true,
        "visibility": "public"
      },
      {
        "name": "create_pull_request",
        "write_action": true,
        "write_enabled": true,
        "visibility": "public"
      }
    ],
    "controller_log": [],
    "summary": {
      "title": "list_tools: completed",
      "bullets": [],
      "next_steps": []
    },
    "user_message": "list_tools: completed"
  }
}
```

Notes:
- The `tools` array is usually much larger than shown here.
- Fields such as `risk_level` or `operation` may appear depending on deployment.

### Example: successful `ensure_workspace_clone`

```json
{
  "result": {
    "branch": "main",
    "reset": true,
    "created": false,
    "controller_log": [],
    "summary": {
      "title": "ensure_workspace_clone: completed",
      "bullets": [],
      "next_steps": []
    },
    "user_message": "ensure_workspace_clone: completed"
  }
}
```

### Example: successful `workspace_create_branch`

```json
{
  "result": {
    "base_ref": "main",
    "new_branch": "docs/detailed-tools-response-examples",
    "checkout": {
      "exit_code": 0,
      "timed_out": false,
      "stdout": "",
      "stderr": "Switched to a new branch 'docs/detailed-tools-response-examples'
"
    },
    "push": {
      "exit_code": 0,
      "timed_out": false,
      "stdout": "branch 'docs/detailed-tools-response-examples' set up to track 'origin/docs/detailed-tools-response-examples'.
",
      "stderr": "To https://github.com/Proofgate-Revocations/chatgpt-mcp-github.git
 * [new branch]      docs/detailed-tools-response-examples -> docs/detailed-tools-response-examples
"
    },
    "summary": {
      "title": "workspace_create_branch: completed",
      "bullets": [],
      "next_steps": []
    },
    "user_message": "workspace_create_branch: completed"
  }
}
```

Notes:
- Command outputs may be truncated in long-running operations (see `stdout_truncated` / `stderr_truncated` fields when present).

### Example: error-shaped response

```json
{
  "text": "Error executing tool open_file_context: ...",
  "is_error": true
}
```

---

## Safety, write actions, and the workspace

There are two categories of tools:

1) Read tools: inspect GitHub, server state, or workspace state.
2) Write tools: mutate GitHub state (issues/PRs/branches) or mutate the workspace filesystem/git state.

Separately, "workspace" tools operate on a persistent, server-side git clone.

Tool registry defaults: this server does not disable any tools by default (empty built-in denylist). Operators may optionally disable specific tools via `MCP_TOOL_DENYLIST` (see `docs/usage.md`).

Recommended practice for changes:

- Use `ensure_workspace_clone` (or a workspace tool that implicitly ensures a clone) and make edits in the persistent clone.
- Run checks with `terminal_command` or `render_shell`.
- Commit/push from the workspace (`commit_workspace` / `commit_workspace_files`).
- Open a PR (`open_pr_for_existing_branch` or `create_pull_request`).

## Quick index

Environment & diagnostics:
- `validate_environment`, `get_server_config`, `get_rate_limit`, `get_user_login`, `ping_extensions`, `get_repo_dashboard`, `get_repo_dashboard_graphql`

Tool introspection:
- `list_tools`, `describe_tool`, `list_all_actions`, `validate_tool_args`

Repositories & search:
- `list_repositories`, `list_repositories_by_installation`, `get_repository`, `list_repository_tree`, `search`, `graphql_query`, `fetch_url`

Files & content caching:
- `get_file_contents`, `fetch_files`, `cache_files`, `get_cached_files`, `download_user_content`

Workspace (persistent clone):
- `ensure_workspace_clone`, `list_workspace_files`, `get_workspace_file_contents`, `set_workspace_file_contents`, `search_workspace`, `terminal_command`, `render_shell`, `get_workspace_changes_summary`, `commit_workspace`, `commit_workspace_files`, `workspace_sync_status`, `workspace_sync_to_remote`, `update_file_from_workspace`

Branches & PRs:
- `create_branch`, `ensure_branch`, `list_branches`, `workspace_create_branch`, `workspace_delete_branch`, `workspace_self_heal_branch`, `workspace_sync_status`, `workspace_sync_to_remote`, `get_branch_summary`, `get_latest_branch_status`, `get_commit_combined_status`, `list_pull_requests`, `create_pull_request`, `open_pr_for_existing_branch`, `recent_prs_for_branch`, `fetch_pr`, `get_pr_info`, `get_pr_overview`, `list_pr_changed_filenames`, `fetch_pr_comments`, `comment_on_pull_request`, `merge_pull_request`, `close_pull_request`, `build_pr_summary`, `update_files_and_open_pr`

Issues:
- `list_recent_issues`, `list_repository_issues`, `list_open_issues_graphql`, `fetch_issue`, `fetch_issue_comments`, `create_issue`, `update_issue`, `comment_on_issue`, `open_issue_context`, `get_issue_overview`, `resolve_handle`, `get_issue_comment_reactions`

Actions / CI:
- `list_workflow_runs`, `list_workflow_runs_graphql`, `get_workflow_run`, `get_workflow_run_overview`, `list_workflow_run_jobs`, `get_job_logs`, `trigger_workflow_dispatch`, `trigger_and_wait_for_workflow`, `wait_for_workflow_run`, `list_recent_failures`, `list_recent_failures_graphql`, `run_tests`, `run_lint_suite`, `run_quality_suite`

Misc file navigation helpers:
- `get_file_slice`, `get_file_with_line_numbers`, `open_file_context`

Administration:
- `authorize_write_actions` (if enabled in your deployment)

---

# Environment & diagnostics

## validate_environment

Purpose: Verify GitHub authentication and core server environment assumptions (token presence, API connectivity, default repo/branch settings when configured).

Inputs: none.

Outputs: A structured report including detected configuration and any problems.

Example:

```json
{"tool":"validate_environment","args":{}}
```

## get_server_config

Purpose: Return a safe summary of server settings (timeouts, concurrency, output limits, and other runtime configuration).

Inputs: none.

Outputs: Configuration snapshot.

Example:

```json
{"tool":"get_server_config","args":{}}
```

## get_rate_limit

Purpose: Return current GitHub API rate limit state for the authenticated token.

Inputs: none.

Outputs: Rate limit buckets and remaining quota.

Example:

```json
{"tool":"get_rate_limit","args":{}}
```

## get_user_login

Purpose: Return the GitHub login for the authenticated token.

Inputs: none.

Outputs: User/installation identity.

Example:

```json
{"tool":"get_user_login","args":{}}
```

## ping_extensions

Purpose: Health-check the MCP server “extensions surface” (used by some deployments to confirm optional integrations are reachable).

Inputs: none.

Outputs: Simple acknowledgement.

Example:

```json
{"tool":"ping_extensions","args":{}}
```

---

# Tool introspection & schema validation

## list_tools

Purpose: List available MCP tools with compact descriptions. Useful for UIs and lightweight discovery.

Inputs:
- `only_write` (bool, default false): show only write-capable tools.
- `only_read` (bool, default false): show only read tools.
- `name_prefix` (string | null): filter tools by prefix.

Outputs: Tool names and short descriptions.

Example:

```json
{"tool":"list_tools","args":{"only_write":true}}
```

## list_all_actions

Purpose: Enumerate the full tool catalog, optionally including the input schemas. This is the most complete introspection endpoint.

Inputs:
- `include_parameters` (bool, default false): include serialized input schemas.
- `compact` (bool | null): reduce output size for UIs.

Outputs: Tool list with metadata and (optionally) schemas.

Example:

```json
{"tool":"list_all_actions","args":{"include_parameters":true}}
```

## describe_tool

Purpose: Get the full schema and metadata for one tool (or a small list of tools) without enumerating everything.

Inputs:
- `name` / `tool_name` (string | null): single tool name.
- `names` (string[] | null): multiple tool names.
- `include_parameters` (bool, default true): include schema.

Outputs: Tool schema and documentation metadata.

Example:

```json
{"tool":"describe_tool","args":{"name":"create_pull_request"}}
```

## validate_tool_args

Purpose: Validate candidate payloads against tool input schemas without running them. Useful for testing and UI preflight validation.

Inputs:
- `tool_name` (string | null): validate one tool.
- `tool_names` (string[] | null): validate several tools (same `payload` applied to each).
- `payload` (object | null): candidate arguments.

Outputs: Validation results and schema excerpt.

Example:

```json
{
  "tool":"validate_tool_args",
  "args":{
    "tool_name":"create_pull_request",
    "payload":{"full_name":"OWNER/REPO","title":"Docs update","head":"docs/my-branch","base":"main"}
  }
}
```

---

# Repositories & search

## list_repositories

Purpose: List repositories visible to the authenticated principal.

Inputs:
- `affiliation` (string | null): e.g. `owner`, `collaborator`, `organization_member`.
- `visibility` (string | null): `all`, `public`, `private`.
- `per_page` (int, default 30), `page` (int, default 1).

Outputs: Repository list.

Example:

```json
{"tool":"list_repositories","args":{"per_page":30,"page":1}}
```

## list_repositories_by_installation

Purpose: List repositories available to a specific GitHub App installation.

Inputs:
- `installation_id` (int): installation identifier.
- `per_page` (int, default 30), `page` (int, default 1).

Outputs: Repository list.

Example:

```json
{"tool":"list_repositories_by_installation","args":{"installation_id":123456}}
```

## get_repository

Purpose: Fetch repository metadata including default branch and permission summary.

Inputs:
- `full_name` (string): `owner/repo`.

Outputs: Repository object.

Example:

```json
{"tool":"get_repository","args":{"full_name":"OWNER/REPO"}}
```

## list_repository_tree

Purpose: List repository tree entries (files and directories) for a ref.

Inputs:
- `full_name` (string)
- `ref` (string, default `main`)
- `path_prefix` (string | null): restrict to a subdirectory.
- `recursive` (bool, default true)
- `max_entries` (int, default 1000)
- `include_blobs` (bool, default true), `include_trees` (bool, default true)

Outputs: Tree entries (paths and types).

Example:

```json
{"tool":"list_repository_tree","args":{"full_name":"OWNER/REPO","ref":"main","path_prefix":"docs"}}
```

## search

Purpose: GitHub search endpoint wrapper. Supports searching code, repositories, issues, commits, or users.

Inputs:
- `query` (string): GitHub search query syntax.
- `search_type` (string, default `code`): `code`, `repositories`, `issues`, `commits`, `users`.
- `per_page` (int, default 30), `page` (int, default 1)
- `sort` (string | null), `order` (`asc` | `desc` | null)

Outputs: GitHub search results.

Example:

```json
{"tool":"search","args":{"search_type":"code","query":"filename:Detailed_Tools.md"}}
```

## graphql_query

Purpose: Run an arbitrary GitHub GraphQL query.

Inputs:
- `query` (string)
- `variables` (object | null)

Outputs: GraphQL response.

Example:

```json
{"tool":"graphql_query","args":{"query":"query($owner:String!,$name:String!){repository(owner:$owner,name:$name){defaultBranchRef{name}}}","variables":{"owner":"OWNER","name":"REPO"}}}
```

## fetch_url

Purpose: Fetch an external HTTPS URL through the server (useful for retrieving upstream docs or JSON payloads).

Inputs:
- `url` (string)

Outputs: HTTP status, headers, and text/body (subject to server limits).

Example:

```json
{"tool":"fetch_url","args":{"url":"https://example.com"}}
```

---

# Files & content caching (GitHub API)

## get_file_contents

Purpose: Fetch a single file from GitHub (Contents API) and decode it to UTF-8 text.

Inputs:
- `full_name` (string)
- `path` (string)
- `ref` (string, default `main`)
- `branch` (string | null): optional alias/override depending on deployment.

Outputs: File content (decoded) plus metadata.

Example:

```json
{"tool":"get_file_contents","args":{"full_name":"OWNER/REPO","path":"README.md","ref":"main"}}
```

## fetch_files

Purpose: Fetch multiple files from GitHub in one call.

Inputs:
- `full_name` (string)
- `paths` (string[]): list of paths
- `ref` (string, default `main`)

Outputs: Map of path → decoded content and metadata.

Example:

```json
{"tool":"fetch_files","args":{"full_name":"OWNER/REPO","ref":"main","paths":["README.md","docs/usage.md"]}}
```

## cache_files

Purpose: Fetch and cache file payloads in server memory to avoid repeated GitHub reads.

Inputs:
- `full_name` (string)
- `paths` (string[])
- `ref` (string, default `main`)
- `refresh` (bool, default false): bypass existing cache.

Outputs: Cache status per file.

Example:

```json
{"tool":"cache_files","args":{"full_name":"OWNER/REPO","ref":"main","paths":["README.md"],"refresh":true}}
```

## get_cached_files

Purpose: Retrieve cached file payloads for a repository/ref without re-fetching.

Inputs:
- `full_name` (string)
- `paths` (string[])
- `ref` (string, default `main`)

Outputs: Cached entries (if present).

Example:

```json
{"tool":"get_cached_files","args":{"full_name":"OWNER/REPO","ref":"main","paths":["README.md"]}}
```

## download_user_content

Purpose: Download user-provided content (for example a `sandbox:/...` file reference) and return base64-encoded content.

Inputs:
- `content_url` (string)

Outputs: Base64-encoded content and metadata.

Example:

```json
{"tool":"download_user_content","args":{"content_url":"sandbox:/mnt/data/input.txt"}}
```

---

# Workspace (persistent clone)

## ensure_workspace_clone

Purpose: Ensure a persistent server-side clone exists for a repo/ref. Optionally reset it to match the remote ref.

Inputs:
- `full_name` (string | null): `owner/repo`. If omitted, deployment defaults may apply.
- `ref` (string, default `main`)
- `reset` (bool, default false): if true, recreate/reset the workspace clone.

Outputs: Clone status and the effective branch checked out.

Example:

```json
{"tool":"ensure_workspace_clone","args":{"full_name":"OWNER/REPO","ref":"main","reset":true}}
```

## list_workspace_files

Purpose: List files and (optionally) directories in the persistent workspace clone.

Inputs:
- `full_name` (string | null)
- `ref` (string, default `main`)
- `path` (string, default empty): directory within repo
- `max_depth` / `max_files` / `max_results` (int | null)
- `include_dirs` (bool, default false)
- `include_hidden` (bool, default false)

Outputs: File paths.

Example:

```json
{"tool":"list_workspace_files","args":{"full_name":"OWNER/REPO","ref":"my-branch","path":"docs","include_dirs":true,"max_depth":2}}
```

## get_workspace_file_contents

Purpose: Read a file from the persistent workspace clone.

Inputs:
- `full_name` (string | null)
- `ref` (string, default `main`)
- `path` (string): file path

Outputs: UTF-8 text, size, and decoding metadata.

Example:

```json
{"tool":"get_workspace_file_contents","args":{"full_name":"OWNER/REPO","ref":"my-branch","path":"README.md"}}
```

## set_workspace_file_contents

Purpose: Replace a workspace file’s contents (full overwrite). This is the preferred write primitive for deterministic edits.

Inputs:
- `full_name` (string | null)
- `ref` (string, default `main`)
- `path` (string)
- `content` (string)
- `create_parents` (bool, default true)

Outputs: Write acknowledgement.

Example:

```json
{"tool":"set_workspace_file_contents","args":{"full_name":"OWNER/REPO","ref":"my-branch","path":"docs/note.md","content":"# Title\n\nBody\n"}}
```

## search_workspace

Purpose: Search text files in the workspace clone.

Inputs:
- `full_name` (string | null)
- `ref` (string, default `main`)
- `query` (string)
- `path` (string, default empty): restrict to a subtree
- `case_sensitive` (bool, default false)
- `max_results` (int | null)
- `regex` (bool | null):
  - null: treat as regex if valid, else literal
  - false: literal
  - true: strict regex

Outputs: Matched file paths and excerpts (bounded).

Example:

```json
{"tool":"search_workspace","args":{"full_name":"OWNER/REPO","ref":"main","query":"MCP_TOOL_DENYLIST","regex":false}}
```

## terminal_command

Purpose: Run a shell command in the persistent workspace clone. Use for tests, formatting, and local git operations.

Inputs:
- `full_name` (string | null)
- `ref` (string, default `main`)
- `command` (string)
- `timeout_seconds` (number, default 300)
- `workdir` (string | null): working directory within repo
- `use_temp_venv` (bool, default true)
- `installing_dependencies` (bool, default false)

Outputs: Exit code, stdout/stderr (truncated to configured limits).

Example:

```json
{"tool":"terminal_command","args":{"full_name":"OWNER/REPO","ref":"my-branch","command":"pytest -q","timeout_seconds":600}}
```

## render_shell

Purpose: Render-centric shell runner that can clone and optionally create a branch, then run a command. Use when your deployment is on Render and you want logs consistent with Render execution.

Inputs (commonly used):
- `full_name` (string | null)
- `command` (string)
- `create_branch` (string | null): create and checkout a new branch before running
- `push_new_branch` (bool, default true)
- `ref` (string, default `main`)
- `workdir` (string | null)

Outputs: Exit code and output.

Example:

```json
{"tool":"render_shell","args":{"full_name":"OWNER/REPO","ref":"main","create_branch":"docs/my-branch","command":"python -m pytest -q"}}
```

## get_workspace_changes_summary

Purpose: Summarize modified/added/deleted/renamed/untracked files in the workspace clone.

Inputs:
- `full_name` (string)
- `ref` (string, default `main`)
- `path_prefix` (string | null)
- `max_files` (int, default 200)

Outputs: Categorized file lists.

Example:

```json
{"tool":"get_workspace_changes_summary","args":{"full_name":"OWNER/REPO","ref":"my-branch"}}
```

## commit_workspace

Purpose: Commit workspace changes and optionally push them.

Inputs:
- `full_name` (string | null)
- `ref` (string, default `main`)
- `message` (string)
- `add_all` (bool, default true)
- `push` (bool, default true)

Outputs: Git commit/push status.

Example:

```json
{"tool":"commit_workspace","args":{"full_name":"OWNER/REPO","ref":"my-branch","message":"Update Detailed_Tools.md","add_all":true,"push":true}}
```

## commit_workspace_files

Purpose: Commit and optionally push specific files from the workspace (more controlled than `commit_workspace`).

Inputs:
- `full_name` (string)
- `files` (string[]): paths to include
- `ref` (string, default `main`)
- `message` (string)
- `push` (bool, default true)

Outputs: Commit/push status.

Example:

```json
{"tool":"commit_workspace_files","args":{"full_name":"OWNER/REPO","ref":"my-branch","files":["Detailed_Tools.md"],"message":"Refresh tool documentation"}}
```

## update_file_from_workspace

Purpose: Sync a file from the persistent workspace clone back into the GitHub repository via the Contents API.

When to use: If you edited a file in the workspace but want to update GitHub without pushing a git commit (or when a repo policy requires Contents API updates).

Inputs:
- `full_name` (string)
- `workspace_path` (string): path in workspace clone
- `target_path` (string): destination path in repo
- `branch` (string)
- `message` (string)

Outputs: GitHub update result.

Example:

```json
{"tool":"update_file_from_workspace","args":{"full_name":"OWNER/REPO","workspace_path":"Detailed_Tools.md","target_path":"Detailed_Tools.md","branch":"my-branch","message":"Sync doc update"}}
```

---

# Branches & pull requests

## create_branch

Purpose: Create a branch in a repository via the GitHub API.

Inputs:
- `full_name` (string)
- `branch` (string): new branch name
- `from_ref` (string, default `main`): base ref

Outputs: Branch creation result.

Example:

```json
{"tool":"create_branch","args":{"full_name":"OWNER/REPO","branch":"feature/my-branch","from_ref":"main"}}
```

## ensure_branch

Purpose: Ensure a branch exists; create it if missing.

Inputs: same as `create_branch`.

Outputs: Branch status.

Example:

```json
{"tool":"ensure_branch","args":{"full_name":"OWNER/REPO","branch":"feature/my-branch","from_ref":"main"}}
```

## list_branches

Purpose: Enumerate branches for a repository.

Inputs:
- `full_name` (string)
- `per_page` (int, default 100), `page` (int, default 1)

Outputs: Branch list.

Example:

```json
{"tool":"list_branches","args":{"full_name":"OWNER/REPO","per_page":100,"page":1}}
```

## workspace_create_branch

Purpose: Create a branch using the workspace clone (git), optionally pushing it to origin. Useful when direct API branch creation is constrained.

Inputs:
- `full_name` (string | null)
- `base_ref` (string, default `main`)
- `new_branch` (string)
- `push` (bool, default true)

Outputs: Checkout and push logs.

Example:

```json
{"tool":"workspace_create_branch","args":{"full_name":"OWNER/REPO","base_ref":"main","new_branch":"feature/my-branch","push":true}}
```

## workspace_delete_branch

Purpose: Delete a non-default branch using the workspace clone (git), optionally also removing the remote branch depending on deployment.

Inputs:
- `full_name` (string | null)
- `branch` (string): branch to delete

Outputs: Deletion status.

Example:

```json
{"tool":"workspace_delete_branch","args":{"full_name":"OWNER/REPO","branch":"feature/my-branch"}}
```

## workspace_self_heal_branch

Purpose: Recover from a corrupted/mangled workspace git state by diagnosing, optionally deleting the problematic branch, resetting the base, and recreating a fresh branch.

Inputs (commonly used):
- `full_name` (string | null)
- `branch` (string): problematic branch
- `base_ref` (string, default `main`)
- `new_branch` (string | null): name of the recovered branch
- `discard_uncommitted_changes` (bool, default true)
- `delete_mangled_branch` (bool, default true)
- `reset_base` (bool, default true)
- `enumerate_repo` (bool, default true)
- `dry_run` (bool, default false)

Outputs: Plain-language recovery logs.

Example:

```json
{"tool":"workspace_self_heal_branch","args":{"full_name":"OWNER/REPO","branch":"feature/broken","new_branch":"feature/broken-healed"}}
```

## workspace_sync_status

Purpose: Report whether the workspace clone is ahead/behind the remote branch and whether there are local uncommitted changes.

Inputs:
- `full_name` (string | null)
- `ref` (string, default `main`)
- `branch` (string | null, alias for `ref`)

Outputs: Local/remote SHAs, ahead/behind counts, working tree cleanliness, and status lines.

Example:

```json
{"tool":"workspace_sync_status","args":{"full_name":"OWNER/REPO","ref":"main"}}
```

## workspace_sync_to_remote

Purpose: Hard-reset the workspace clone to match the remote branch, optionally discarding local changes and unpushed commits.

Inputs:
- `full_name` (string | null)
- `ref` (string, default `main`)
- `discard_local_changes` (bool, default false): must be true to drop uncommitted changes or unpushed commits.
- `branch` (string | null, alias for `ref`)

Outputs: Sync snapshots before and after the reset.

Example:

```json
{"tool":"workspace_sync_to_remote","args":{"full_name":"OWNER/REPO","ref":"main","discard_local_changes":true}}
```

## get_branch_summary

Purpose: Return ahead/behind and divergence summary for a branch relative to a base.

Inputs:
- `full_name` (string)
- `branch` (string)
- `base` (string, default `main`)

Outputs: Ahead/behind counts and related metadata.

Example:

```json
{"tool":"get_branch_summary","args":{"full_name":"OWNER/REPO","branch":"feature/my-branch","base":"main"}}
```

## get_latest_branch_status

Purpose: Return a compact snapshot of a branch’s status relative to base, including recent PR/CI signals when available.

Inputs: same as `get_branch_summary`.

Outputs: Status snapshot.

Example:

```json
{"tool":"get_latest_branch_status","args":{"full_name":"OWNER/REPO","branch":"feature/my-branch","base":"main"}}
```

## get_commit_combined_status

Purpose: Fetch combined GitHub status checks for a commit ref.

Inputs:
- `full_name` (string)
- `ref` (string): commit SHA or ref

Outputs: Combined status summary.

Example:

```json
{"tool":"get_commit_combined_status","args":{"full_name":"OWNER/REPO","ref":"HEAD"}}
```

## list_pull_requests

Purpose: List pull requests in a repository with optional filtering.

Inputs:
- `full_name` (string)
- `state` (`open` | `closed` | `all`, default `open`)
- `head` (string | null): filter by head branch
- `base` (string | null): filter by base branch
- `per_page` (int, default 30), `page` (int, default 1)

Outputs: PR list.

Example:

```json
{"tool":"list_pull_requests","args":{"full_name":"OWNER/REPO","state":"open","head":"OWNER:feature/my-branch"}}
```

## create_pull_request

Purpose: Open a new pull request from `head` into `base`.

Inputs:
- `full_name` (string)
- `title` (string)
- `head` (string): branch name or `owner:branch`
- `base` (string, default `main`)
- `body` (string | null)
- `draft` (bool, default false)

Outputs: PR object.

Example:

```json
{"tool":"create_pull_request","args":{"full_name":"OWNER/REPO","title":"Refresh tool docs","head":"docs/detailed-tools-refresh","base":"main","draft":false}}
```

## open_pr_for_existing_branch

Purpose: Idempotently open (or reuse) a PR for an existing branch. If a matching open PR already exists, returns it instead of creating a duplicate.

Inputs:
- `full_name` (string)
- `branch` (string): head branch
- `base` (string, default `main`)
- `title` (string | null)
- `body` (string | null)
- `draft` (bool, default false)

Outputs: PR object.

Example:

```json
{"tool":"open_pr_for_existing_branch","args":{"full_name":"OWNER/REPO","branch":"docs/detailed-tools-refresh","base":"main","title":"Refresh detailed tools documentation"}}
```

## recent_prs_for_branch

Purpose: Return recent PRs associated with a branch, grouped by open/closed state.

Inputs:
- `full_name` (string)
- `branch` (string)
- `include_closed` (bool, default false)
- `per_page_open` (int, default 20)
- `per_page_closed` (int, default 5)

Outputs: Grouped PR lists.

Example:

```json
{"tool":"recent_prs_for_branch","args":{"full_name":"OWNER/REPO","branch":"docs/detailed-tools-refresh","include_closed":true}}
```

## fetch_pr

Purpose: Fetch a pull request by number.

Inputs:
- `full_name` (string)
- `pull_number` (int)

Outputs: PR object.

Example:

```json
{"tool":"fetch_pr","args":{"full_name":"OWNER/REPO","pull_number":123}}
```

## get_pr_info

Purpose: Lightweight PR metadata fetch (title, state, refs, mergeability where available).

Inputs:
- `full_name` (string)
- `pull_number` (int)

Outputs: PR metadata.

Example:

```json
{"tool":"get_pr_info","args":{"full_name":"OWNER/REPO","pull_number":123}}
```

## get_pr_overview

Purpose: High-level PR overview including changed files and CI status.

Inputs:
- `full_name` (string)
- `pull_number` (int)

Outputs: Aggregated overview.

Example:

```json
{"tool":"get_pr_overview","args":{"full_name":"OWNER/REPO","pull_number":123}}
```

## list_pr_changed_filenames

Purpose: List filenames changed in a PR.

Inputs:
- `full_name` (string)
- `pull_number` (int)
- `per_page` (int, default 100), `page` (int, default 1)

Outputs: List of paths.

Example:

```json
{"tool":"list_pr_changed_filenames","args":{"full_name":"OWNER/REPO","pull_number":123}}
```

## fetch_pr_comments

Purpose: Fetch PR issue comments.

Inputs:
- `full_name` (string)
- `pull_number` (int)
- `per_page` (int, default 30), `page` (int, default 1)

Outputs: Comments.

Example:

```json
{"tool":"fetch_pr_comments","args":{"full_name":"OWNER/REPO","pull_number":123,"per_page":30,"page":1}}
```

## comment_on_pull_request

Purpose: Post a comment on a pull request.

Inputs:
- `full_name` (string)
- `number` (int): PR number
- `body` (string)

Outputs: Comment object.

Example:

```json
{"tool":"comment_on_pull_request","args":{"full_name":"OWNER/REPO","number":123,"body":"Reviewed; looks good."}}
```

## merge_pull_request

Purpose: Merge a pull request.

Inputs:
- `full_name` (string)
- `number` (int)
- `merge_method` (`merge` | `squash` | `rebase`, default `squash`)
- `commit_title` (string | null)
- `commit_message` (string | null)

Outputs: Merge result.

Example:

```json
{"tool":"merge_pull_request","args":{"full_name":"OWNER/REPO","number":123,"merge_method":"squash"}}
```

## close_pull_request

Purpose: Close a pull request without merging.

Inputs:
- `full_name` (string)
- `number` (int)

Outputs: Close result.

Example:

```json
{"tool":"close_pull_request","args":{"full_name":"OWNER/REPO","number":123}}
```

## build_pr_summary

Purpose: Build a normalized JSON summary suitable for a PR description. This is a helper for consistent, structured PR bodies.

Inputs:
- `full_name` (string)
- `ref` (string): branch/ref being summarized
- `title` (string), `body` (string)
- optional: `changed_files` (string[] | null), `tests_status` (string | null), `lint_status` (string | null), `breaking_changes` (bool | null)

Outputs: Normalized JSON object.

Example:

```json
{"tool":"build_pr_summary","args":{"full_name":"OWNER/REPO","ref":"docs/detailed-tools-refresh","title":"Refresh tool docs","body":"Expanded tool reference.","tests_status":"not run"}}
```

## update_files_and_open_pr

Purpose: Convenience tool that writes/commits multiple files (server-side) and opens a PR in one call.

Inputs:
- `full_name` (string)
- `title` (string)
- `files` (object[]): tool-defined file update objects (varies by deployment)
- `base_branch` (string, default `main`)
- `new_branch` (string | null)
- `body` (string | null)
- `draft` (bool, default false)

Outputs: Commit results and PR object.

Example:

```json
{
  "tool":"update_files_and_open_pr",
  "args":{
    "full_name":"OWNER/REPO",
    "title":"Update docs",
    "base_branch":"main",
    "new_branch":"docs/update-docs",
    "files":[{"path":"docs/note.md","content":"Hello"}]
  }
}
```

---

# Issues

## list_recent_issues

Purpose: List recent issues for the authenticated principal (assigned, created, mentioned, etc.).

Inputs:
- `filter` (string, default `assigned`)
- `state` (string, default `open`)
- `per_page` (int, default 30), `page` (int, default 1)

Outputs: Issue list.

Example:

```json
{"tool":"list_recent_issues","args":{"filter":"assigned","state":"open"}}
```

## list_repository_issues

Purpose: List issues in a repository.

Inputs:
- `full_name` (string)
- `state` (string, default `open`)
- `labels` (string[] | null)
- `assignee` (string | null)
- `per_page` (int, default 30), `page` (int, default 1)

Outputs: Issue list.

Example:

```json
{"tool":"list_repository_issues","args":{"full_name":"OWNER/REPO","state":"open"}}
```

## list_open_issues_graphql

Purpose: List open issues (excluding PRs) via GraphQL, with cursor-based pagination.

Inputs:
- `full_name` (string)
- `state` (string, default `open`) — `open`, `closed`, or `all`
- `per_page` (int, default 30)
- `cursor` (string | null) — pass the prior response `page_info.end_cursor`

Outputs: Issue list + pagination info.

Example:

```json
{"tool":"list_open_issues_graphql","args":{"full_name":"OWNER/REPO","state":"open","per_page":25}}
```

## fetch_issue

Purpose: Fetch a single issue by number.

Inputs:
- `full_name` (string)
- `issue_number` (int)

Outputs: Issue object.

Example:

```json
{"tool":"fetch_issue","args":{"full_name":"OWNER/REPO","issue_number":42}}
```

## fetch_issue_comments

Purpose: Fetch comments on an issue.

Inputs:
- `full_name` (string)
- `issue_number` (int)
- `per_page` (int, default 30), `page` (int, default 1)

Outputs: Comment list.

Example:

```json
{"tool":"fetch_issue_comments","args":{"full_name":"OWNER/REPO","issue_number":42,"per_page":30,"page":1}}
```

## create_issue

Purpose: Create a new issue.

Inputs:
- `full_name` (string)
- `title` (string)
- `body` (string | null)
- `labels` (string[] | null)
- `assignees` (string[] | null)

Outputs: Created issue.

Example:

```json
{"tool":"create_issue","args":{"full_name":"OWNER/REPO","title":"Bug: ...","body":"Steps to reproduce...","labels":["bug"]}}
```

## update_issue

Purpose: Update issue fields (title/body/state/labels/assignees).

Inputs:
- `full_name` (string)
- `issue_number` (int)
- optional: `title`, `body`, `state` (`open` | `closed` | null), `labels`, `assignees`

Outputs: Updated issue.

Example:

```json
{"tool":"update_issue","args":{"full_name":"OWNER/REPO","issue_number":42,"state":"closed"}}
```

## comment_on_issue

Purpose: Post a comment on an issue.

Inputs:
- `full_name` (string)
- `issue_number` (int)
- `body` (string)

Outputs: Comment object.

Example:

```json
{"tool":"comment_on_issue","args":{"full_name":"OWNER/REPO","issue_number":42,"body":"Acknowledged; investigating."}}
```

## open_issue_context

Purpose: Return an issue plus related branches and pull requests. Useful for navigation ("what code/PRs are associated with this issue?").

Inputs:
- `full_name` (string)
- `issue_number` (int)

Outputs: Issue + related artifacts.

Example:

```json
{"tool":"open_issue_context","args":{"full_name":"OWNER/REPO","issue_number":42}}
```

## get_issue_overview

Purpose: High-level issue overview including related branches/PRs and checklist items.

Inputs:
- `full_name` (string)
- `issue_number` (int)

Outputs: Aggregated overview.

Example:

```json
{"tool":"get_issue_overview","args":{"full_name":"OWNER/REPO","issue_number":42}}
```

## resolve_handle

Purpose: Resolve a user handle in a repository context (used by some navigation helpers).

Inputs:
- `full_name` (string)
- `handle` (string)

Outputs: Resolved identity.

Example:

```json
{"tool":"resolve_handle","args":{"full_name":"OWNER/REPO","handle":"octocat"}}
```

## get_issue_comment_reactions

Purpose: Fetch reactions for a specific issue comment.

Inputs:
- `full_name` (string)
- `comment_id` (int)
- `per_page` (int, default 30), `page` (int, default 1)

Outputs: Reactions.

Example:

```json
{"tool":"get_issue_comment_reactions","args":{"full_name":"OWNER/REPO","comment_id":987654321}}
```

---

# Actions / CI

## list_workflow_runs

Purpose: List recent GitHub Actions workflow runs for a repository.

Inputs:
- `full_name` (string)
- optional: `branch` (string | null), `status` (string | null), `event` (string | null)
- `per_page` (int, default 30), `page` (int, default 1)

Outputs: Workflow run list.

Example:

```json
{"tool":"list_workflow_runs","args":{"full_name":"OWNER/REPO","branch":"main","per_page":10}}
```

## list_workflow_runs_graphql

Purpose: List recent GitHub Actions workflow runs via GraphQL with cursor-based pagination.

Inputs:
- `full_name` (string)
- `per_page` (int, default 30)
- `cursor` (string | null) — pass the prior response `page_info.end_cursor`
- optional: `branch` (string | null) — filter to a branch locally

Outputs: Workflow run list + pagination info.

Example:

```json
{"tool":"list_workflow_runs_graphql","args":{"full_name":"OWNER/REPO","per_page":20}}
```

## get_workflow_run

Purpose: Retrieve a specific workflow run including conclusion and timing.

Inputs:
- `full_name` (string)
- `run_id` (int)

Outputs: Workflow run.

Example:

```json
{"tool":"get_workflow_run","args":{"full_name":"OWNER/REPO","run_id":123456789}}
```

## get_workflow_run_overview

Purpose: Summarize a workflow run for CI triage (metadata + jobs + failures + longest jobs).

Inputs:
- `full_name` (string)
- `run_id` (int)
- `max_jobs` (int, default 500)

Outputs: Aggregated overview.

Example:

```json
{"tool":"get_workflow_run_overview","args":{"full_name":"OWNER/REPO","run_id":123456789}}
```

## list_workflow_run_jobs

Purpose: List jobs within a workflow run.

Inputs:
- `full_name` (string)
- `run_id` (int)
- `per_page` (int, default 30), `page` (int, default 1)

Outputs: Job list.

Example:

```json
{"tool":"list_workflow_run_jobs","args":{"full_name":"OWNER/REPO","run_id":123456789,"per_page":30,"page":1}}
```

## get_job_logs

Purpose: Fetch raw logs for a specific workflow job.

Inputs:
- `full_name` (string)
- `job_id` (int)

Outputs: Log payload.

Example:

```json
{"tool":"get_job_logs","args":{"full_name":"OWNER/REPO","job_id":987654321}}
```

## trigger_workflow_dispatch

Purpose: Trigger a workflow dispatch event on a given ref.

Inputs:
- `full_name` (string)
- `workflow` (string): file name or numeric ID
- `ref` (string)
- `inputs` (object | null)

Outputs: Dispatch acknowledgement.

Example:

```json
{"tool":"trigger_workflow_dispatch","args":{"full_name":"OWNER/REPO","workflow":"ci.yml","ref":"main","inputs":{"run_full":true}}}
```

## trigger_and_wait_for_workflow

Purpose: Trigger a workflow and block until it completes or timeout.

Inputs: same as `trigger_workflow_dispatch` plus:
- `timeout_seconds` (int, default 900)
- `poll_interval_seconds` (int, default 10)

Outputs: Completion result.

Example:

```json
{"tool":"trigger_and_wait_for_workflow","args":{"full_name":"OWNER/REPO","workflow":"ci.yml","ref":"main","timeout_seconds":900}}
```

## wait_for_workflow_run

Purpose: Poll a workflow run until completion.

Inputs:
- `full_name` (string)
- `run_id` (int)
- `timeout_seconds` (int, default 900)
- `poll_interval_seconds` (int, default 10)

Outputs: Final run state.

Example:

```json
{"tool":"wait_for_workflow_run","args":{"full_name":"OWNER/REPO","run_id":123456789,"timeout_seconds":900}}
```

## list_recent_failures

Purpose: List recent failed or cancelled workflow runs for quicker CI debugging.

Inputs:
- `full_name` (string)
- `branch` (string | null)
- `limit` (int, default 10)

Outputs: Filtered run list.

Example:

```json
{"tool":"list_recent_failures","args":{"full_name":"OWNER/REPO","branch":"main","limit":5}}
```

## list_recent_failures_graphql

Purpose: List recent failed/cancelled workflow runs via GraphQL.

Inputs:
- `full_name` (string)
- `branch` (string | null)
- `limit` (int, default 10)

Outputs: Filtered run list.

Example:

```json
{"tool":"list_recent_failures_graphql","args":{"full_name":"OWNER/REPO","branch":"main","limit":5}}
```

## run_tests

Purpose: Run a test command in the workspace clone (default `pytest`).

Inputs:
- `full_name` (string)
- `ref` (string, default `main`)
- `test_command` (string, default `pytest`)
- `timeout_seconds` (number, default 600)
- `workdir` (string | null)
- `use_temp_venv` (bool, default true)
- `installing_dependencies` (bool, default false)

Outputs: Command output.

Example:

```json
{"tool":"run_tests","args":{"full_name":"OWNER/REPO","ref":"my-branch","test_command":"pytest -q","timeout_seconds":600}}
```

## run_lint_suite

Purpose: Run a lint command in the workspace clone (default `ruff check .`).

Inputs:
- `full_name` (string)
- `ref` (string, default `main`)
- `lint_command` (string, default `ruff check .`)
- `timeout_seconds` (number, default 600)
- `workdir` (string | null)

Outputs: Command output.

Example:

```json
{"tool":"run_lint_suite","args":{"full_name":"OWNER/REPO","ref":"my-branch","lint_command":"ruff check ."}}
```

## run_quality_suite

Purpose: Run tests + lint in one call.

Inputs:
- `full_name` (string)
- `ref` (string, default `main`)
- `test_command` (string, default `pytest`)
- `lint_command` (string, default `ruff check .`)
- `timeout_seconds` (number, default 600)

Outputs: Aggregated command output.

Example:

```json
{"tool":"run_quality_suite","args":{"full_name":"OWNER/REPO","ref":"my-branch","test_command":"pytest -q","lint_command":"ruff check ."}}
```

---

## get_repo_dashboard

Purpose: A compact multi-signal dashboard for a repository (repo metadata, PRs, issues, recent workflows, top-level tree).

Inputs:
- `full_name` (string)
- `branch` (string | null)

Outputs: Dashboard object.

Example:

```json
{"tool":"get_repo_dashboard","args":{"full_name":"OWNER/REPO","branch":"main"}}
```

## get_repo_dashboard_graphql

Purpose: GraphQL-backed fallback for `get_repo_dashboard` when REST helpers are blocked.

Inputs:
- `full_name` (string)
- `branch` (string | null)

Outputs: Dashboard object.

Example:

```json
{"tool":"get_repo_dashboard_graphql","args":{"full_name":"OWNER/REPO","branch":"main"}}
```

---

# File navigation helpers (workspace slices)

These helpers are designed to produce citation-friendly excerpts.

## get_file_slice

Purpose: Return a slice of a repository file with stable boundaries.

Inputs:
- `full_name` (string)
- `path` (string)
- `ref` (string | null)
- `start_line` (int, default 1)
- `max_lines` (int, default 200)

Outputs: Text slice.

Example:

```json
{"tool":"get_file_slice","args":{"full_name":"OWNER/REPO","path":"README.md","ref":"main","start_line":1,"max_lines":50}}
```

## get_file_with_line_numbers

Purpose: Return a file excerpt with line numbers for manual editing.

Inputs:
- `full_name` (string)
- `path` (string)
- `ref` (string | null)
- `start_line` (int, default 1)
- `max_lines` (int, default 5000)

Outputs: Line-numbered excerpt.

Example:

```json
{"tool":"get_file_with_line_numbers","args":{"full_name":"OWNER/REPO","path":"README.md","ref":"main","start_line":1,"max_lines":200}}
```

## open_file_context

Purpose: Return a citation-friendly slice with line numbers and content entries.

Inputs:
- `full_name` (string)
- `path` (string)
- `ref` (string | null)
- `start_line` (int | null)
- `max_lines` (int, default 200)

Outputs: Structured slice.

Example:

```json
{"tool":"open_file_context","args":{"full_name":"OWNER/REPO","path":"README.md","ref":"main","start_line":1,"max_lines":120}}
```

---

# Reactions

## get_pr_reactions

Purpose: Fetch reactions for a pull request.

Inputs:
- `full_name` (string)
- `pull_number` (int)
- `per_page` (int, default 30), `page` (int, default 1).

Outputs: Reaction list.

Example:

```json
{"tool":"get_pr_reactions","args":{"full_name":"OWNER/REPO","pull_number":123}}
```

## get_pr_review_comment_reactions

Purpose: Fetch reactions for a pull request review comment.

Inputs:
- `full_name` (string)
- `comment_id` (int)
- `per_page` (int, default 30), `page` (int, default 1).

Outputs: Reaction list.

Example:

```json
{"tool":"get_pr_review_comment_reactions","args":{"full_name":"OWNER/REPO","comment_id":123456789}}
```

---

# Repository creation & file operations

## create_repository

Purpose: Create a new repository. Supports templates and payload overrides that mirror GitHub’s “New repository” UI.

Inputs (selected):
- `name` (string)
- optional: `owner` (string | null), `owner_type` (`auto` | `user` | `org`)
- optional: `description`, `homepage`, `visibility` (`public` | `private` | `internal`)
- optional: `auto_init` (bool, default true)
- optional: `gitignore_template`, `license_template`
- optional: `topics` (string[] | null)
- optional: `template_full_name` (string | null)
- optional: `clone_to_workspace` (bool, default false), `clone_ref` (string | null)

Outputs: Created repository metadata.

Example:

```json
{"tool":"create_repository","args":{"name":"my-new-repo","visibility":"private","auto_init":true,"topics":["mcp","github"]}}
```

## create_file

Purpose: Create a file in a GitHub repository via the Contents API.

Inputs:
- `full_name` (string)
- `path` (string)
- `content` (string)
- `branch` (string, default `main`)
- `message` (string | null)

Outputs: GitHub create result.

Example:

```json
{"tool":"create_file","args":{"full_name":"OWNER/REPO","path":"docs/new.md","content":"# New\n","branch":"main","message":"Add docs"}}
```

## move_file

Purpose: Move/rename a file in a GitHub repository via the Contents API.

Inputs:
- `full_name` (string)
- `from_path` (string)
- `to_path` (string)
- `branch` (string, default `main`)
- `message` (string | null)

Outputs: GitHub move result.

Example:

```json
{"tool":"move_file","args":{"full_name":"OWNER/REPO","from_path":"docs/old.md","to_path":"docs/new.md","branch":"main","message":"Rename doc"}}
```

## delete_file

Purpose: Delete a file in a GitHub repository via the Contents API.

Inputs:
- `full_name` (string)
- `path` (string)
- `branch` (string, default `main`)
- `message` (string, optional)
- `if_missing` (`error` | `noop`, default `error)

Outputs: GitHub delete result.

Example:

```json
{"tool":"delete_file","args":{"full_name":"OWNER/REPO","path":"docs/tmp.md","branch":"main","if_missing":"noop"}}
```

## apply_text_update_and_commit

Purpose: Update a single file’s full content on a branch and commit the change in one call.

Inputs:
- `full_name` (string)
- `path` (string)
- `updated_content` (string)
- `branch` (string, default `main`)
- `message` (string | null)
- `return_diff` (bool, default false)

Outputs: Commit result (and optionally diff).

Example:

```json
{"tool":"apply_text_update_and_commit","args":{"full_name":"OWNER/REPO","path":"README.md","updated_content":"# Title\n","branch":"main","message":"Update README"}}
```

---

# Administration

## authorize_write_actions

Purpose: Toggle the server’s global “write allowed” gate and refresh tool metadata so clients see correct read/write affordances.

Notes:
- Not all deployments expose this tool.
- Use with caution; disabling write actions prevents tools like `create_issue`, `merge_pull_request`, and workspace write primitives from running.

Inputs:
- `approved` (bool, default true)

Outputs: Acknowledgement.

Example:

```json
{"tool":"authorize_write_actions","args":{"approved":true}}
```

---

# Appendix: hidden/internal tools

Some deployments mark certain tools as hidden. If your client can call them, they behave similarly to their public equivalents.
