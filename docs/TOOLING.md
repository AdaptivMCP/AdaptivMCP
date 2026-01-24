# Tooling: MCP tools, API tools, and standard workflows

This server exposes a catalog of **tools** that can be invoked by an MCP-capable client (for example, an IDE agent, a CLI, or ChatGPT acting as a controller).

In practice, you will encounter three related concepts:

- **MCP tool (authoritative concept)**: a server-side function registered with the MCP server (typically via `@mcp_tool`). This is the *real* capability.
- **API tool (client wrapper concept)**: a client-side wrapper that calls an MCP tool through a transport (often HTTP) and presents it as an “API tool” to the controller.
- **Both**: some deployments expose the same capability via MCP-native transport and via an HTTP tool registry; clients may call either transport, but the underlying operation is the same MCP tool.

## Definitions

### MCP tools

**MCP tools** are registered on the server and surfaced through the tool registry.

Characteristics:

- Live on the server.
- Are the source of truth for behavior, auth, and safety checks.
- May be read-only or write-capable (`write_action=True`).
- May operate via GitHub APIs, Render APIs, or the server-side workspace mirror.

### API tools

**API tools** are not a separate server capability. They are a client integration layer.

Common patterns:

- A controller (e.g., ChatGPT) calls an HTTP endpoint that forwards to an MCP tool.
- The controller labels the call as an “API tool” call, even though the operation is still a server-registered MCP tool.

### Both

A capability is effectively **both** when:

- It is defined as an MCP tool server-side, and
- It is reachable through multiple transports (MCP-native and HTTP tool registry).

Operationally:

- You should document behavior once (as an MCP tool), and treat transport differences as implementation details.

## Tool families and when to use them

This repository broadly exposes two families:

1. **Main tools** (`github_mcp/main_tools/`): API-backed operations (GitHub, Actions, Render, etc.).
2. **Workspace tools** (`github_mcp/workspace_tools/`): persistent repo mirror operations (filesystem edits, git porcelain, running commands).

### Main tools: what they are

Main tools map to platform APIs and are best for:

- Reading and writing repository content through GitHub APIs.
- Managing issues / PRs.
- Inspecting or triggering GitHub Actions runs.
- Using Render APIs to deploy, roll back, and fetch logs.

**Trade-offs**:

- GitHub Contents API is excellent for direct file CRUD, but it cannot run tests or inspect the filesystem holistically.

### Workspace tools: what they are

Workspace tools operate on a **server-side persistent git clone** keyed by `(full_name, ref)`.

Use workspace tools for:

- Multi-file refactors.
- Grep/ripgrep across the repo.
- Running `pytest`, lint, typecheck, or build steps.
- Generating diffs from the working tree.
- Higher-level workflows that create a branch, apply edits, run quality, and open PRs.

**Important invariant**:

- Workspace clones are keyed by `ref`. If you change branches inside a clone without “re-keying”, later tool calls to a different `ref` would operate on a different directory. The workspace git tools and workflows are designed to avoid this footgun.

## Read-only vs write-capable tools

- **Read-only tools** (`write_action=False`) are safe for inspection.
- **Write-capable tools** (`write_action=True`) mutate state (workspace filesystem, git history, GitHub resources, Render services).

When automating, prefer:

1. Read-only inspection
2. Local/workspace edits with explicit diffs
3. Commit + push on a feature branch
4. PR creation back to base

## Common workflows

### Workflow A: “sync remote and discard changes” (reset workspace to remote)

Use when the workspace mirror has local modifications you want to drop and you want the mirror to match origin.

- Primary tool: `workspace_sync_to_remote(discard_local_changes=true)`
- Alternative: `workspace_sync_bidirectional(discard_local_changes=true)` when you also want to resolve “behind/diverged” cases with a single helper.

Recommended steps:

1. Inspect status: `workspace_sync_status`
2. Reset mirror: `workspace_sync_to_remote(discard_local_changes=true)`
3. Verify clean: `workspace_git_status` or `workspace_sync_status`

Classification: **MCP tool**, typically invoked via **API tool wrapper** in some clients (effectively **both**).

### Workflow B: “edit files and open a PR” (end-to-end)

Use when you want an ergonomic safe default path.

- Primary tool: `workspace_apply_ops_and_open_pr`

Recommended steps:

1. Prepare plan context (optional): `workspace_task_plan`
2. Apply operations on a feature branch + run quality: `workspace_apply_ops_and_open_pr(run_quality=true)`
3. Review PR output and CI.

Classification: **MCP tool**, often called via an API wrapper (effectively **both**).

### Workflow C: “manual edit loop in workspace mirror”

Use for iterative development and debugging.

1. Ensure clone: `ensure_workspace_clone`
2. Search and inspect:
   - `rg_search_workspace`, `list_workspace_files`, `read_workspace_file_with_line_numbers`
3. Edit:
   - `set_workspace_file_contents` (replace full file)
   - `edit_workspace_text_range` / `replace_workspace_text` (surgical edits)
   - `apply_patch` / `apply_workspace_diff` (patch application)
4. Validate:
   - `run_lint_suite` / `run_tests` / `run_quality_suite` or `terminal_command`
5. Commit and push:
   - `commit_workspace` or `workspace_git_commit` + `workspace_git_push`
6. Open PR:
   - `commit_and_open_pr_from_workspace` or `workspace_open_pr_from_workspace`

Classification: **MCP tools**, usually accessible via **both**.

### Workflow D: “API-only file update” (no workspace)

Use when the change is small and you do not need a filesystem or test execution.

1. Read file: `get_file_contents`
2. Update file: `apply_text_update_and_commit` (simple replace) or `create_file` / `delete_file`
3. Open PR if needed: `update_files_and_open_pr` or `create_pull_request`

Classification: **MCP tools** backed by GitHub APIs; often presented to controllers as **API tools**.

## Tool operation reference

Below is a pragmatic mapping for documentation and user guidance.

### Workspace mirror (filesystem + git + command execution)

Read-only:

- `get_workspace_file_contents`, `read_workspace_file_excerpt`, `read_workspace_file_sections`, `read_workspace_file_with_line_numbers`
- `list_workspace_files`, `find_workspace_paths`, `search_workspace`
- `rg_list_workspace_files`, `rg_search_workspace`
- `workspace_git_status`, `workspace_git_log`, `workspace_git_show`, `workspace_git_blame`, `workspace_git_branches`, `workspace_git_tags`, `workspace_git_stash_list`
- `workspace_sync_status`, `workspace_git_diff`, `workspace_change_report`
- `workspace_venv_status`

Write-capable:

- File edits: `set_workspace_file_contents`, `edit_workspace_text_range`, `replace_workspace_text`, `apply_patch`, `apply_workspace_diff`, `apply_workspace_operations`
- File/dir ops: `create_workspace_folders`, `delete_workspace_paths`, `delete_workspace_folders`, `move_workspace_paths`
- Git ops: `workspace_git_checkout`, `workspace_git_stage`, `workspace_git_unstage`, `workspace_git_commit`, `workspace_git_reset`, `workspace_git_clean`, `workspace_git_restore`, `workspace_git_merge`, `workspace_git_rebase`, `workspace_git_cherry_pick`, `workspace_git_revert`, `workspace_git_pull`, `workspace_git_push`, `workspace_git_stash_save`, `workspace_git_stash_pop`, `workspace_git_stash_apply`, `workspace_git_stash_drop`
- Branch lifecycle: `workspace_create_branch`, `workspace_delete_branch`, `workspace_self_heal_branch`
- Sync helpers: `workspace_sync_to_remote`, `workspace_sync_bidirectional`
- Venv lifecycle: `workspace_venv_start`, `workspace_venv_stop`

Workflows:

- `commit_workspace`, `commit_workspace_files`
- `commit_and_open_pr_from_workspace`
- `workspace_apply_ops_and_open_pr`, `workspace_manage_folders_and_open_pr`
- Task orchestration: `workspace_task_plan`, `workspace_task_apply_edits`, `workspace_task_execute`
- Multi-branch orchestration: `workspace_batch`

Transport classification: these are **MCP tools**, frequently invoked via an **API tool wrapper** in controller environments (effectively **both**).

### GitHub API tools (repository/PR/issue/actions)

Read-only:

- Repository: `get_repository`, `list_branches`, `list_repository_tree`, `get_repo_dashboard`
- Files: `get_file_contents`, `get_file_excerpt`, `fetch_files`, `get_cached_files`
- Search: `search`, `graphql_query`
- Issues/PRs: `fetch_issue`, `fetch_pr`, `get_pr_info`, `list_pull_requests`, `list_repository_issues`, `list_open_issues_graphql`
- Actions: `list_workflow_runs`, `get_workflow_run`, `get_workflow_run_overview`, `list_workflow_run_jobs`, `get_job_logs`, `list_recent_failures`

Write-capable:

- Files: `create_file`, `delete_file`, `move_file`, `apply_text_update_and_commit`, `cache_files(refresh=true)`
- Branches/PRs: `create_branch`, `ensure_branch`, `create_pull_request`, `open_pr_for_existing_branch`, `update_files_and_open_pr`, `merge_pull_request`, `close_pull_request`
- Issues: `create_issue`, `update_issue`, `comment_on_issue`
- PR comments: `comment_on_pull_request`
- Actions: `trigger_workflow_dispatch`, `trigger_and_wait_for_workflow`

Transport classification: these are **MCP tools** backed by GitHub APIs, but are commonly presented as **API tools** to controller clients.

### Render tools (deployment)

Read-only:

- `list_render_owners`, `list_render_services`, `get_render_service`, `list_render_deploys`, `get_render_deploy`, `get_render_logs`, `list_render_logs`

Write-capable:

- `create_render_deploy`, `cancel_render_deploy`, `rollback_render_deploy`, `restart_render_service`, `create_render_service`, `set_render_service_env_vars`, `patch_render_service`

Transport classification: **MCP tools**; often called via an API wrapper (effectively **both**).

## Recommended documentation language

When describing capabilities, prefer:

- “This server exposes an MCP tool named `<tool_name>`…”
- If needed: “Some clients call it via an API wrapper, but the underlying operation is the same MCP tool.”

This avoids confusion between the transport (API wrapper) and the server capability (MCP tool).
