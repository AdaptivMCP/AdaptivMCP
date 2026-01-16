# Tool robustness and usage patterns

This note documents server-side input validation and common usage flows for the workspace (repo mirror), GitHub, and Render tools.

## Workspace (repo mirror)

The workspace tools operate on a persistent server-side clone (“repo mirror”). A common write flow is:

1. `ensure_workspace_clone` (create or re-create the repo mirror if needed)
2. Modify files via `set_workspace_file_contents` or `apply_patch`
3. Inspect changes via `get_workspace_changes_summary`
4. Commit and push via `commit_workspace` / `commit_workspace_files`
5. Open a PR via `create_pull_request` (or `commit_and_open_pr_from_workspace`)

Input validation and guardrails:

- All file path inputs are validated as repo-relative paths and are required to resolve within the repo root (path traversal is rejected).
- `set_workspace_file_contents` requires a non-empty `path` and writes using UTF-8 text.
- `delete_workspace_paths` requires a non-empty `paths` list.
  - Directories are refused unless `allow_recursive=true`.
  - Missing paths are ignored only when `allow_missing=true`.
- `apply_patch` rejects patches that attempt to write outside the repo mirror.

Operational notes:

- If the upstream branch diverged (rebases/force-push), use `ensure_workspace_clone` with `reset=true` to recreate the mirror.
- If unified diff patches are inconvenient for your client, `delete_workspace_paths` provides a direct deletion path.

## GitHub tools

The GitHub tools primarily wrap the REST and GraphQL APIs.

Validation and reliability:

- Repository identifiers are validated as `owner/repo`.
- Git refs are normalized so that “default branch” behavior is consistent across controller and arbitrary repos.
- REST pagination inputs are clamped to safe bounds (e.g., `per_page` 1–100 where applicable; `page` >= 1).
- For long-running or multi-call summaries (e.g., dashboards), helpers degrade gracefully and return section-level errors instead of failing the entire call.

Common usage patterns:

- `get_repo_dashboard` / `get_repo_dashboard_graphql` for quick triage and orientation.
- `cache_files` + `get_cached_files` for repeated reads of the same content during an interactive session.
- For CI triage, `get_workflow_run_overview` and then `get_job_logs` for untruncated job output.

## Render tools

The Render tools wrap Render’s public API.

Validation and safety controls:

- Render ids are validated by expected prefixes (`srv-` for services, `dpl-` for deploys).
- Pagination inputs are clamped to safe bounds (`limit` has a maximum; `cursor` is optional).
- `create_render_deploy` enforces a mutually exclusive selection for deploy source:
  - Provide `commit_id` for repo-backed services, or
  - Provide `image_url` for image-backed services.
- `get_render_logs` validates timestamps as ISO8601 strings when provided, and clamps `limit`.

Common usage patterns:

- Start discovery with `list_render_owners` and `list_render_services`.
- Use `list_render_deploys` to locate relevant deploy ids before calling `get_render_deploy`, `cancel_render_deploy`, or `rollback_render_deploy`.
- For incident response, couple `get_render_deploy` (state/metadata) with `get_render_logs` (runtime symptoms).
