# Tool robustness and usage patterns

This note documents server-side input validation and usage patterns for the workspace (repo mirror), GitHub, and Render tools.

This document uses the terminology defined in `docs/terminology.md`.

## Workspace (repo mirror)

The workspace tools operate on a persistent server-side clone (“repo mirror”).
They cover repository working-copy management, file edits, command execution,
and git operations (commit/push/PR creation).

Representative tools:

- Repo mirror management: `ensure_workspace_clone`, `workspace_sync_status`, `workspace_sync_to_remote`
- Branch management: `workspace_create_branch`
- File edits: `set_workspace_file_contents`, `apply_patch`, `apply_workspace_operations`
- Change inspection: `get_workspace_changes_summary`
- Commit/push: `commit_workspace`, `commit_workspace_files`
- PR creation: `create_pull_request`, `commit_and_open_pr_from_workspace`

Input validation and guardrails:

- All file path inputs are validated as repo-relative paths and are required to resolve within the repo root (path traversal is rejected).
- `set_workspace_file_contents` requires a non-empty `path` and writes using UTF-8 text.
- `delete_workspace_paths` requires a non-empty `paths` list.
- `move_workspace_paths` moves (renames) multiple paths in one call.
- `apply_workspace_operations` batches writes, edits, moves, and deletions with optional rollback.
  - Directories are refused unless `allow_recursive=true`.
  - Missing paths are ignored only when `allow_missing=true`.
- `apply_patch` rejects patches that attempt to write outside the repo mirror.

Operational notes:

- When the upstream branch diverges (rebases/force-push), `ensure_workspace_clone(reset=true)` recreates the mirror from the selected remote ref.
- When unified diff patches are not a good fit for a client integration, `delete_workspace_paths` provides a direct deletion operation.

Diagnostics:

- `validate_environment` returns an operator-friendly report including token detection,
  tool registry sanity checks, and (optionally) an installed dependency snapshot.

## GitHub tools

The GitHub tools primarily wrap the REST and GraphQL APIs.

Validation and reliability:

- Repository identifiers are validated as `owner/repo`.
- Git refs are normalized so that “default branch” behavior is consistent across controller and arbitrary repos.
- REST pagination inputs are clamped to safe bounds (e.g., `per_page` 1–100 where applicable; `page` >= 1).
- For long-running or multi-call summaries (e.g., dashboards), helpers degrade gracefully and return section-level errors instead of failing the entire call.

Representative combinations:

- `get_repo_dashboard` / `get_repo_dashboard_graphql` for repository-level status and orientation.
- `cache_files` + `get_cached_files` for repeated reads of the same content during a session.
- CI inspection: `get_workflow_run_overview`, `get_job_logs`.

Response shaping:

Some deployments enable response shaping for ChatGPT-hosted connectors (see
`docs/usage.md`). When enabled, mapping tool results may be normalized to
include `ok` / `status` and large nested payloads may be truncated.

## Logging and failure semantics

The server emits provider-facing tool logs intended for hosted log UIs (for
example Render) and incident triage.

Events (structured `event` field):

- `tool_call_started` (INFO): emitted when a tool wrapper begins execution.
- `tool_call_completed` (INFO): emitted when a tool returns a non-error result.
- `tool_call_completed_with_warnings` (WARNING): emitted when a tool returns a
  warning result.
- `tool_call_failed` (ERROR): emitted when a tool raises an exception or returns
  an explicit error payload.

Failure classification:

- A mapping result is treated as an error when it includes any of:
  - `ok=false`
  - `status` in `error|failed|failure`
  - a non-empty `error` string
  - terminal-style outcomes: `exit_code != 0` or `timed_out=true` (either at the
    top level or under a nested `result` mapping)

Structured errors:

- Exceptions are converted to a compatibility-preserving payload that always
  includes a top-level single-line `error` string and an `error_detail` object
  with `category`, `code`, `retryable`, `help`, and redacted `debug` fields.

- Tool wrappers attach an `error_detail.trace` object with:
  - `call_id`: shortened call identifier

Tracebacks:

- Provider logs can include `exc_info` for failures when
  `GITHUB_MCP_LOG_EXC_INFO=1` (default: enabled locally; disabled on Render).
- Tool payloads include tracebacks only when `GITHUB_MCP_INCLUDE_TRACEBACK` is
  enabled (default: enabled locally; disabled on Render).

## Render tools

The Render tools wrap Render’s public API.

Validation and safety controls:

- Render ids are validated by expected prefixes (`srv-` for services, `dpl-` for deploys).
- Pagination inputs are clamped to safe bounds (`limit` has a maximum; `cursor` is optional).
- `create_render_deploy` enforces a mutually exclusive selection for deploy source:
  - `commit_id` is accepted for repo-backed services, or
  - `image_url` is accepted for image-backed services.
- `get_render_logs` validates timestamps as ISO8601 strings when provided, and clamps `limit`.

Representative combinations:

- Inventory/inspection: `list_render_owners`, `list_render_services`, `list_render_deploys`.
- Deploy lifecycle: `get_render_deploy`, `cancel_render_deploy`, `rollback_render_deploy`.
- Runtime diagnostics: `get_render_deploy`, `get_render_logs`.
