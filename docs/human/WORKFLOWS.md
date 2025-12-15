# Adaptiv Controller workflows

This document describes how to use the Adaptiv Controller GitHub MCP server from ChatGPT at high power. It is the engine side playbook. Your personal controller prompts on the ChatGPT side describe style and preferences, while this file describes how to drive the tools safely and effectively.

It is written for

- People running an Adaptiv Controller style GPT, such as a personal controller named Joeys GitHub.
- Advanced assistants that need precise, repeatable workflows over GitHub.
- Engineers who want to move quickly while keeping the controller safe.

For internals and guarantees, see `docs/human/ARCHITECTURE_AND_SAFETY.md`.
For prompt and snapshot guidance, see `docs/assistant/ASSISTANT_DOCS_AND_SNAPSHOTS.md`.
---

## 1. Golden rules

All workflows should respect these rules, especially when touching the controller repo itself, `Proofgate-Revocations/chatgpt-mcp-github`.

1. Never write directly to the main branch of the controller repo.
   - All work happens on feature branches, such as `issue-146-health-and-metrics`, `fix-branch-default-main`, or `docs-update-workflows`.
   - The main branch is the canonical production branch.

2. Assume read only until proven otherwise.
   - The server may start with `WRITE_ALLOWED` set to false.
   - Never assume you can write without checking.

3. Keep work on feature branches and in pull requests.
   - Create a feature branch before any write.
   - Keep changes on that branch reviewable.
   - Open a PR for any non trivial change and let a human merge and delete branches.

4. Verify every write.
   - Rely on built in verification in write tools.
   - Never assume a write succeeded without checking.

5. Use run_quality_suite, run_lint_suite, and terminal_command for real work.
   - Treat `run_quality_suite` as your primary way to run the project's default test suite (for example `pytest`) on a branch.
   - Use `run_lint_suite` for lint/static analysis (for example `ruff check .`, `mypy` or other project specific commands).
   - Use `terminal_command` for additional inspection commands, focused test invocations, linters, and dependency installs when necessary.
   - Do not ask humans to type commands or fiddle with blank lines or quoting. Handle multi-line commands, patches, and retries
     with the workspace tools yourself.

6. Summarize and keep a paper trail.
   - Summarize plans, changes, and outcomes in issues and pull requests.
   - Link related issues, docs, and pull requests for traceability.

---

## 2. Discovery and bootstrapping

When a controller like Joeys GitHub attaches to this server, it should do a small amount of discovery before making any assumptions.

Recommended sequence

1. Call `get_server_config`.
   - Understand defaults (controller repo, main branch, timeouts, feature flags, write gate).
   - Pay attention to the `write_allowed` and `auto_approve` configuration.

2. Call `list_all_actions` with `include_parameters` set to true. This controller guarantees that each tool will expose a non-null `input_schema` object in that response. When the underlying MCP tool does not publish an explicit input schema, the server either synthesizes a minimal `{type: "object", properties: {}}` schema or uses a hand-authored schema for key navigation tools like `list_workflow_runs` and `list_recent_failures` so assistants can still reason about required fields and filters.
   - Discover the full tool surface, including MCP tools and any GitHub specific helpers.
   - Learn parameter shapes and required fields.

3. Call `list_write_tools`.
   - Identify which tools perform writes and are subject to write gating.
   - Treat them with extra care.

4. Optionally call `validate_environment`.
   - Confirm that GitHub access works and controller repo defaults match expectations.

5. Read the core docs.
   - Fetch and read this file, `docs/assistant/ASSISTANT_HANDOFF.md`, `docs/human/ARCHITECTURE_AND_SAFETY.md`, `docs/assistant/ASSISTANT_DOCS_AND_SNAPSHOTS.md`, `docs/human/UPGRADE_NOTES.md`, `docs/human/SELF_HOSTED_SETUP.md`, `docs/human/SELF_HOSTING_DOCKER.md`, and `docs/human/OPERATIONS.md`.

### Validating tool arguments before writes

For tools that accept structured JSON arguments, especially write-tagged tools, assistants SHOULD validate payloads before calling them:

- Use `describe_tool` or `list_all_actions(include_parameters=true)` to understand the expected JSON schema for a tool.
- Call `validate_tool_args` with `tool_name` and the candidate `args` object to get structured validation feedback without executing the tool.
- For tools like `list_workflow_runs` / `list_recent_failures`, the controller provides a hand-authored JSON schema even when the underlying MCP tool does not publish one, so missing fields (for example required fields) will surface as explicit validation errors.
- Treat `validate_tool_args` as part of the default workflow for complex tools and repair flows, not just a rescue tool after a failure.

When validation succeeds (`valid: true` and `errors: []`), proceed to the actual tool call. When it fails, use the returned `errors` array to repair the payload before retrying.

### Handling tool argument JSON errors

If the client or ChatGPT host returns `ToolInputError: Could not parse args as JSON`, the last tool call payload was not valid JSON. To recover quickly:

- Keep tool arguments as a pure JSON object with double-quoted keys/strings and no Markdown or code fences.
- Strip trailing comments or explanations from the arguments payload—only the JSON object should be passed to the tool.
- When in doubt, run `validate_json_string` on the candidate arguments to confirm the host will accept them before retrying the tool call.
- Treat `validate_json_string` as part of the default JSON routine, not an optional repair tool. Assistants should automatically validate any non-trivial JSON payload (tool arguments, raw JSON responses, or config blobs) before emitting it so that hosts never see malformed payloads in the first place.

---

## 3. Branching and pull request discipline

Branching and pull request discipline is the backbone of safe usage.

### 3.1 Creating feature branches

Use `ensure_branch` to create or reuse feature branches. Typical patterns

- `docs/self-hosting-docker`
- `fix/dockerfile-apt-run`
- `feature/controller-contract-2025-03-16`
- `issue-123-fix-run-command-timeout`

Assistants should

- Create branches off `main` unless there is a clear reason not to.
- Use human friendly names that reflect the work.
- Avoid long lived branches that drift far from `main`.

### 3.2 Committing and pushing

When operating inside a workspace

- Use `run_quality_suite`, `run_lint_suite`, or `terminal_command` for inspection, edits, and tests.

Best practices
- Keep commits focused and well described.
- Reference issues or PRs in commit messages when relevant.
- Do not commit unrelated changes in the same commit.

### 3.3 Opening pull requests

Use the PR tools to open and update pull requests. A typical flow

1. Complete changes on a feature branch.
2. Run tests and any relevant CLI checks via `run_quality_suite` (the default quality gate), `run_lint_suite` (lint/type checks), or `terminal_command` / `run_tests`.
4. Include in the PR body
   - Summary of changes.
   - Motivation and context.
   - Tests run and results.
   - Known limitations or follow ups.

Humans typically review, merge, and delete branches.

---

## 4. Diff-based editing tools

Assistants SHOULD avoid using `terminal_command` to embed large shell/Python
scripts to modify files. This is brittle because those scripts must be
embedded inside JSON strings and are easy to mis-escape.

Multi-line edits are routine. Use the diff helpers below to apply
them directly instead of treating them as tricky or deferring them to
humans.

Instead, assistants SHOULD use these tools:

- Patch strings are normalized when applying: the server will unescape diffs that were accidentally pasted as a single line with literal \\n sequences, and it will strip common trailing Markdown/JSON artifacts (like code fences or `}}`) when the input looks like a diff.
- `apply_text_update_and_commit` – full-file overwrite; use only when intentionally regenerating the entire file.
- `update_files_and_open_pr` – commit multiple files and open a PR in one call.

### 4.1 Tool selection for file edits

Use this table to choose the right tool path when editing files:

| Use case                      | Recommended tools                                                          |
|-------------------------------|----------------------------------------------------------------------------|
| Regenerate whole doc from spec| `apply_text_update_and_commit` (full-file overwrite)                     |
| Multiple files in one change  | `update_files_and_open_pr` (optionally preceded by diff builders)        |

In general, prefer diff/section-based edits for existing files. Reserve `apply_text_update_and_commit` for cases where you truly own the whole file content and intend to replace it entirely.
Typical pattern for a single file:

1. Read the current file:
   - `get_file_contents` (or `get_file_slice` for large files).
2. Let the assistant generate the updated full content locally.
3. Call `apply_text_update_and_commit` with:
   - `full_name`
   - `path`
   - `updated_content`
   - `branch`
   - `message`
4. Optionally use `create_pull_request` / `open_pr_for_existing_branch`.

For complex edits to large files, use:


`terminal_command`, `run_quality_suite`, and `run_lint_suite` SHOULD be used primarily for:

- Tests (`pytest`, linters, type checkers) via `run_quality_suite` for the default test command, or `terminal_command` for custom/test-specific invocations.
- Lint/static analysis via `run_lint_suite` when you want a consistent entry point for style/type checks.
- Small shell commands (`ls`, `grep`, diagnostics).
- NOT for large inline patch scripts.
---

## 5. Repository specific workflows

This section describes common workflows for this controller repo itself, `Proofgate-Revocations/chatgpt-mcp-github`.

### 5.1 Updating docs

1. Create a docs branch from `main` (for example `docs/update-handoff-and-workflows`).
2. Use `terminal_command` to inspect and edit `ASSISTANT_HANDOFF.md`, `docs/WORKFLOWS.md`, and related files.
3. Keep changes focused and incremental.
4. Run any documentation tooling or linters if present.
5. Use `commit_workspace` to commit changes to the docs branch.

### 5.2 Medium sized file commits (payload conscious)

When you want to test or exercise medium sized documentation or code commits without flooding the client or model context with huge payloads:

1. Prefer branch scoped edits.
   - Create a feature or docs branch dedicated to the experiment.
2. Choose a medium sized target file (for example this file or `docs/ASSISTANT_HAPPY_PATHS.md`).
3. Make structured but modest edits.
   - Add or adjust a subsection.
   - Avoid rewriting the entire file unless that is the purpose of the change.
   - `return_diff` set to `false` when you only need verification metadata.
   - Brief, descriptive commit messages.
5. Open a PR from the experiment branch into `main` and verify that the diff and metadata look reasonable.

### 5.3 Updating the controller contract

1. Create a dedicated branch for contract changes.
2. Update the contract source and related docs.
3. Ensure that version numbers and compatibility notes are updated.
4. Run tests and schema validation as appropriate.
5. Open a PR and flag it as a contract change.

### 5.4 Adjusting server configuration or defaults

1. Create a branch for configuration changes.
2. Update configuration files, `.env.example`, and relevant docs.
3. If Docker or deployment manifests are updated, keep them in sync with documentation like `docs/SELF_HOSTED_SETUP.md` and `docs/SELF_HOSTING_DOCKER.md`.
4. Run a local or staging deployment if possible and verify `healthz` and basic workflows.
5. Open a PR with a clear explanation of configuration changes.

---

## 6. Multi repository workflows

When using Adaptiv Controller against multiple repositories (for example personal projects and the controller repo itself)

- Use repository scoped tools and be explicit about `full_name` when necessary.
- Keep branches and issues separate per repo.
- Summarize cross repo changes in PRs and issues where appropriate.

Typical pattern

1. For each repository, establish its own feature branch for the work.
2. Run repo local tests and checks.
3. Open PRs in each repo and reference each other when appropriate.
4. Let humans merge in the order that makes sense for deployment.

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


## 7. Troubleshooting and stuck workflows

When a workflow stalls or fails repeatedly

1. Stop repeating the same failing tool call.
2. Summarize the errors and outputs you have seen.
3. Re read relevant docs and the controller contract.
4. Use `validate_tool_args` and `validate_environment` to rule out schema and configuration issues.
   - For PR problems specifically, check the `controller_pr_endpoint` check in `validate_environment`.
5. Check branch and issue state with `get_branch_summary` and `open_issue_context`.
6. When PR tooling itself seems broken (for example repeated timeouts from `create_pull_request`), run `pr_smoke_test` to exercise the full branch + commit + PR path in the live environment.
7. Propose smaller, more observable next steps.
8. Ask the human for input when ambiguity remains.

### 7.x Self-healing a mangled workspace branch

If a workspace clone becomes inconsistent mid-flow (for example: wrong branch checked out, merge/rebase in progress, conflicts stuck, repeated git errors), use:

- `workspace_self_heal_branch(full_name=..., branch=...)`

This tool returns a plain-language `steps` log describing exactly what happened (diagnosis, deletion/reset, new branch name, fresh clone path) and a small repo `snapshot` so the assistant can quickly rebuild context on the new branch.

For UI-friendly observability of long workflows, combine it with:

- `get_recent_tool_events(include_success=true)` which returns `narrative` strings derived from `user_message`.

Remember that this file is the engine side playbook. Personal controllers can adjust tone, verbosity, and other stylistic choices, but they should not contradict the safety and workflow rules documented here.

---

## 8. 1.0 proof-of-concept: exercised workflows

This section records concrete workflows exercised by an assistant against this controller to validate the 1.0 release. It is not a how-to; it is a "we actually did this" log.

### 8.1 Docs-only change using workspace + terminal_command + commit_workspace

Workflow:

1. Created branch `docs/workflow-poc-1-0b` from `main` using `ensure_branch`.
2. Created or refreshed a workspace for that branch using `ensure_workspace_clone`.
3. Ran `terminal_command` with:
   - `command`: `ls && ls docs && pytest -q`
   - `installing_dependencies`: `false`
   This validated that the workspace contained the repo files and that the test suite passes on this branch.
4. Fetched `docs/WORKFLOWS.md` for context using `get_file_contents` on the branch.
6. Opened a pull request from `docs/workflow-poc-1-0b` into `main` describing the exercised workflow and its purpose as a 1.0 proof-of-concept.

Notes:

- This flow demonstrates that:
  - Docs-only changes on a dedicated branch work end-to-end.
  - `ensure_workspace_clone` + `terminal_command` is sufficient for running the full test suite.
- The PR associated with this workflow can be referenced as a concrete 1.0 validation artifact.
