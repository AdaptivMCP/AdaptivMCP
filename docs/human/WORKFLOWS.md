# Operator workflows

This document is for humans operating the server and for assistants acting as engineers. It describes the expected workflows and the “quality gates” that keep deployments safe.

## Core principles

- The assistant runs the tools; humans do not execute MCP actions.
- Prefer branch-first work + PR review.
- Treat CI as the source of truth. On Render, deploys only occur after CI is green.
- Render logs are user-facing: they should read like an assistant explaining what it’s doing.

## Workflow A: Standard branch-first development

Use this for feature work on customer repos or any repo that is not the live controller engine.

1. **Pre-flight**
   - `get_server_config`
   - `validate_environment`
   - `list_all_actions(include_parameters=true)`

2. **Create or ensure a feature branch**
   - `ensure_branch` / `create_branch`

3. **Create/refresh workspace**
   - `ensure_workspace_clone(full_name=..., ref=<branch>, reset=true)`

4. **Discovery and implementation**
   - Inspect with `get_file_slice` / `get_file_with_line_numbers`
   - Edit with `terminal_command` in the workspace

5. **Quality gates**
   - `run_lint_suite`
   - `run_tests`
   - `run_quality_suite` (recommended prior to PR)

6. **Commit and push**
   - `commit_workspace` / `commit_workspace_files`

7. **Open PR**
   - `build_pr_summary` → `open_pr_for_existing_branch`

## Workflow B: Live main-branch mode (controller repo)

This is a special workflow used when the repo being edited is the controller engine itself (this repository) and you explicitly decide to ship directly to `main`.

**Rule:** treat every push as a production deploy.

1. **Pre-flight**
   - `validate_environment` (confirm revision metadata)
   - `list_render_logs` (confirm the service is running and logs are readable)

2. **Work in a clean workspace**
   - `ensure_workspace_clone(full_name=<controller repo>, ref=main, reset=true)`

3. **Implement changes**
   - Keep changes small and scoped.
   - Prefer workspace edits over large patch payloads.

4. **Run quality gates locally**
   - `run_lint_suite`
   - `run_quality_suite`

5. **Commit + push to main**
   - `commit_workspace` / `commit_workspace_files`

6. **Wait for CI, then redeploy**
   - Confirm GitHub Actions is green (workflows complete).
   - Render redeploy starts after CI. Full start after redeploy typically takes several minutes.

7. **Verify the running service**
   - Poll `list_render_logs(limit=100, direction='backward')` roughly every 60 seconds.
   - You should see:
     - the new revision booting
     - the service reaching a steady state
     - tool calls producing clean, user-facing logs

If CI is red, the service will not auto-redeploy and the server will remain on the previous healthy revision.

## Session logs workflow

Session logs are repo-local Markdown files under `session_logs/`.

Expectations:

- Every meaningful commit should leave a readable audit trail in session logs.
- Entries should answer:
  - What changed?
  - Why did it change?
  - How was it tested?
  - What should be verified after deploy?

In this repo, workspace commit helpers automatically append a structured session entry after successful commits.

## Render operations (quick reference)

### Read logs

- Use `list_render_logs` (requires `RENDER_API_KEY`).
- Render’s `/logs` endpoint requires an `ownerId`.
  - Set `RENDER_OWNER_ID` in env, or pass `ownerId=`.

### Confirm a redeploy

- Watch for a new boot sequence in `list_render_logs`.
- Confirm `/healthz` reports expected controller defaults.

