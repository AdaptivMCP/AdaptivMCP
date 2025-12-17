# Assistant happy paths

This file is a playbook of common workflows for assistants using the Adaptiv Controller GitHub MCP server.

Use `describe_tool` for exact schemas.

---

## 1) Read-only triage (fast)

1. `get_repo_dashboard` (high-signal overview)
2. `list_recent_issues` or `list_pull_requests`
3. `get_pr_overview` / `get_issue_overview`
4. If CI is involved:
   - `list_recent_failures` or `get_workflow_run_overview`

Goal: decide *what to do next* before touching the workspace.

---

## 2) Standard code change (branch + PR)

1. `ensure_branch` (feature branch)
2. `ensure_workspace_clone`
3. Edit in the workspace:
   - `terminal_command` (edit files, run formatters, etc.)
4. Quality gates:
   - `run_quality_suite` (preferred)
5. Commit + push:
   - `commit_workspace` (or `commit_workspace_files`)
6. Open PR:
   - `open_pr_for_existing_branch` (or `create_pull_request`)
7. CI triage if needed:
   - `list_workflow_runs`, `get_workflow_run_overview`, `get_job_logs`

---

## 3) Small doc-only change (fast PR)

1. `ensure_branch`
2. `ensure_workspace_clone`
3. Edit:
   - `terminal_command`
4. Commit:
   - `commit_workspace_files` (limit to the doc files)
5. Open PR:
   - `open_pr_for_existing_branch`

---

## 4) Fix failing CI

1. Find the failing run:
   - `list_recent_failures`
2. Pull details:
   - `get_workflow_run_overview`
   - `list_workflow_run_jobs` + `get_job_logs`
3. Reproduce locally:
   - `ensure_workspace_clone`
   - `terminal_command` to match the failing step
4. Patch + verify:
   - `run_tests` / `run_lint_suite`
5. Ship via branch + PR.

---

## 5) Render verification after shipping (controller engine repo)

When operating this repo in direct-to-main mode:

1. Run local gates first:
   - `run_quality_suite`
2. Push to `main`.
3. Confirm GitHub Actions is green.
4. Poll Render logs every ~60s until the new revision is running:
   - `list_render_logs`
5. Confirm the service is responding normally:
   - `get_server_config`, `validate_environment`
