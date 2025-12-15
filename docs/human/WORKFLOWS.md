# Workflows

This document describes the recommended workflows for using this MCP GitHub server.

---

## 1. The default loop

1. Create or ensure a branch.
2. Make changes (code/tests/docs) behind that branch.
3. Run lint/tests.
4. Open a PR.
5. Humans review + merge + delete the branch.

---

## 2. Full-file replacement edits (preferred)

This repo intentionally prefers full-file replacement edits over diff/patch editing tools.

Reasoning:

- Git commits already provide diffs in GitHub.
- Patch application in JSON strings is brittle and prone to escaping issues.
- Full-file replacement is simpler, faster, and easier to validate.

Preferred tool paths:

- Workspace path (recommended for most work):
  - `ensure_workspace_clone` → edit files locally → `commit_workspace` / `commit_workspace_files`
- Contents API path (when you intentionally own the whole file content):
  - `get_file_contents` (or `get_file_slice`) → generate updated full text → `apply_text_update_and_commit`

Avoid:

- Diff/patch editing tools for modifying files.
- Embedding large shell/Python patch scripts inside `terminal_command` arguments.

---

## 3. PR creation and review

Before opening a PR:

1. Run tests and any relevant CLI checks via `run_quality_suite` (default quality gate), `run_lint_suite` (lint/type checks), or `terminal_command` / `run_tests`.
2. Summarize what changed and why.
3. Include in the PR body:
   - Summary of changes.
   - Motivation and context.
   - Tests run and results.
   - Known limitations or follow ups.

Humans typically review, merge, and delete branches.

---

## 4. Workspace usage

Assistants SHOULD avoid using `terminal_command` to embed large shell/Python scripts to modify files. This is brittle because those scripts must be embedded inside JSON strings and are easy to mis-escape.

Use `terminal_command`, `run_quality_suite`, and `run_lint_suite` primarily for:

- Tests (`pytest`, linters, type checkers) via `run_quality_suite` for the default suite, or `terminal_command` for custom invocations.
- Lint/static analysis via `run_lint_suite` when you want a consistent entry point.
- Small shell commands (`ls`, `grep`, diagnostics).

---

## 5. Repository specific workflows

This section describes common workflows for this controller repo itself, `Proofgate-Revocations/chatgpt-mcp-github`.

### 5.1 Updating docs

1. Create a docs branch from `main` (for example `docs/update-handoff-and-workflows`).
2. Use `terminal_command` to inspect and edit `docs/**`.
3. Keep changes focused and incremental.
4. Run any documentation tooling or linters if present.
5. Use `commit_workspace` to commit changes to the docs branch.

### 5.2 Updating the controller contract

1. Create a dedicated branch for contract changes.
2. Update the contract source and related docs.
3. Ensure that version numbers and compatibility notes are updated.
4. Run tests and schema validation as appropriate.
5. Open a PR and flag it as a contract change.

### 5.3 Adjusting server configuration or defaults

1. Create a branch for configuration changes.
2. Update configuration files, `.env.example`, and relevant docs.
3. If Docker or deployment manifests are updated, keep them in sync with documentation like `docs/human/SELF_HOSTED_SETUP.md` and `docs/human/SELF_HOSTING_DOCKER.md`.
4. Run a local or staging deployment if possible and verify `healthz` and basic workflows.
5. Open a PR with a clear explanation of configuration changes.

---

## 6. Multi repository workflows

When using this controller against multiple repositories:

- Use repository scoped tools and be explicit about `full_name` when necessary.
- Keep branches and issues separate per repo.
- Summarize cross repo changes in PRs and issues where appropriate.

---

### 6.1 Creating a new repository

Use `create_repository` when an assistant needs to create a brand new repo (personal or org).

Recommended flow

1. Bootstrap:
   - `get_server_config` and `validate_environment`
   - `list_write_tools`
   - If `write_allowed` is false and you need this tool, call `authorize_write_actions`.

2. Create the repository:

   Example (org repo, initialize with README + topics):

   - Tool: `create_repository`
   - Args:
     - `name`: `my-new-repo`
     - `owner`: `my-org`
     - `owner_type`: `org`
     - `description`: `Short description`
     - `visibility`: `private`
     - `auto_init`: `true`
     - `topics`: `["mcp", "automation"]`

3. Advanced settings:
   - For any GitHub REST fields not exposed as first-class params, pass them via:
     - `create_payload_overrides` (sent to the create endpoint)
     - `update_payload_overrides` (sent to `PATCH /repos/{owner}/{repo}`)

4. Optional:
   - Set `clone_to_workspace=true` to clone the repo into the server workspace.

Notes

- Template repos are supported via `template_full_name` (uses `POST /repos/{template}/generate`).
- The tool returns a plain-language `steps` log suitable for UI surfaces.

---

## 7. Troubleshooting and stuck workflows

When a workflow stalls or fails repeatedly:

1. Stop repeating the same failing tool call.
2. Summarize the errors and outputs you have seen.
3. Re read relevant docs and the controller contract.
4. Use `validate_tool_args` and `validate_environment` to rule out schema and configuration issues.
   - For PR problems specifically, check the `controller_pr_endpoint` check in `validate_environment`.
5. Check branch and issue state with `get_branch_summary` and `open_issue_context`.
6. When PR tooling itself seems broken (for example repeated timeouts from `create_pull_request`), run `pr_smoke_test` to exercise the full branch + commit + PR path in the live environment.
7. Propose smaller, more observable next steps.

### 7.x Self-healing a mangled workspace branch

If a workspace clone becomes inconsistent mid-flow (for example: wrong branch checked out, merge/rebase in progress, conflicts stuck, repeated git errors), use:

- `workspace_self_heal_branch(full_name=..., branch=...)`

This tool returns a plain-language `steps` log describing exactly what happened (diagnosis, deletion/reset, new branch name, fresh clone path) and a small repo `snapshot` so the assistant can quickly rebuild context on the new branch.

For UI-friendly observability of long workflows, combine it with:

- `get_recent_tool_events(limit=20, include_success=true)` which returns `narrative` strings derived from `user_message`.

Remember that this file is the engine side playbook. Personal controllers can adjust tone, verbosity, and other stylistic choices, but they should not contradict the safety and workflow rules documented here.
