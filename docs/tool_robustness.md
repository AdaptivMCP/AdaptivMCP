# Tool robustness and usage patterns

This note documents server-side input validation and common usage flows for the workspace (repo mirror), GitHub, and Render tools.

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

- If the upstream branch diverged (rebases/force-push), use `ensure_workspace_clone` with `reset=true` to recreate the mirror.
- If unified diff patches are inconvenient for your client, `delete_workspace_paths` provides a direct deletion path.

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

## Render tools

The Render tools wrap Render’s public API.

Validation and safety controls:

- Render ids are validated by expected prefixes (`srv-` for services, `dpl-` for deploys).
- Pagination inputs are clamped to safe bounds (`limit` has a maximum; `cursor` is optional).
- `create_render_deploy` enforces a mutually exclusive selection for deploy source:
  - Provide `commit_id` for repo-backed services, or
  - Provide `image_url` for image-backed services.
- `get_render_logs` validates timestamps as ISO8601 strings when provided, and clamps `limit`.

Representative combinations:

- Inventory/inspection: `list_render_owners`, `list_render_services`, `list_render_deploys`.
- Deploy lifecycle: `get_render_deploy`, `cancel_render_deploy`, `rollback_render_deploy`.
- Runtime diagnostics: `get_render_deploy`, `get_render_logs`.
