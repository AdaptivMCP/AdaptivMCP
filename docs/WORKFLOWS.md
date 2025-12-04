# Adaptiv Controller workflows

This document describes how to use the Adaptiv Controller GitHub MCP server from ChatGPT at high power. It is the engine side playbook. Your personal controller prompts on the ChatGPT side describe style and preferences, while this file describes how to drive the tools safely and effectively.

It is written for

- People running an Adaptiv Controller style GPT, such as a personal controller named Joeys GitHub.
- Advanced assistants that need precise, repeatable workflows over GitHub.
- Engineers who want to move quickly while keeping the controller safe.

For internals and guarantees, see `docs/ARCHITECTURE_AND_SAFETY.md`.
For prompt and snapshot guidance, see `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md`.

---

## 1. Golden rules

All workflows should respect these rules, especially when touching the controller repo itself, `Proofgate-Revocations/chatgpt-mcp-github`.

1. Never write directly to the main branch of the controller repo.
   - All work happens on feature branches, such as `issue-146-health-and-metrics`, `fix-branch-default-main`, or `docs-update-workflows`.
   - The main branch is the canonical production branch.

2. Assume read only until proven otherwise.
   - The server may start with `WRITE_ALLOWED` set to false.
   - Never assume you can write without checking.

3. Branch first and pull request first.
   - Create a feature branch before any write.
   - Keep changes on that branch reviewable.
   - Open a PR for any non trivial change and let a human merge and delete branches.

4. Verify every write.
   - Rely on built in verification in write tools.
   - Never assume a write succeeded without checking.

5. Use run_command for real work.
   - Treat `run_command` as your primary way to work inside repo workspaces.
   - Use it to inspect files, run tests and linters, apply patches, and install dependencies when necessary.
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

2. Call `list_all_actions` with `include_parameters` set to true.
   - Discover the full tool surface, including MCP tools and any GitHub specific helpers.
   - Learn parameter shapes and required fields.

3. Call `list_write_tools`.
   - Identify which tools perform writes and are subject to write gating.
   - Treat them with extra care.

4. Optionally call `validate_environment`.
   - Confirm that GitHub access works and controller repo defaults match expectations.

5. Read the core docs.
   - Fetch and read this file, `ASSISTANT_HANDOFF.md`, `docs/ARCHITECTURE_AND_SAFETY.md`, `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md`, `docs/UPGRADE_NOTES.md`, `docs/SELF_HOSTED_SETUP.md`, `docs/SELF_HOSTING_DOCKER.md`, and `docs/OPERATIONS.md`.

### Handling tool argument JSON errors

If the client or ChatGPT host returns `ToolInputError: Could not parse args as JSON`, the last tool call payload was not valid JSON. To recover quickly:

- Keep tool arguments as a pure JSON object with double-quoted keys/strings and no Markdown or code fences.
- Strip trailing comments or explanations from the arguments payload—only the JSON object should be passed to the tool.
- When in doubt, run `validate_json_string` on the candidate arguments to confirm the host will accept them before retrying the tool call.

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

- Use `run_command` for inspection, edits, and tests.
- Use `commit_workspace` to stage, commit, and push changes to the feature branch.

Best practices

- Keep commits focused and well described.
- Reference issues or PRs in commit messages when relevant.
- Do not commit unrelated changes in the same commit.

### 3.3 Opening pull requests

Use the PR tools to open and update pull requests. A typical flow

1. Complete changes on a feature branch.
2. Run tests and any relevant CLI checks via `run_command` or `run_tests`.
3. Use a pull request tool to open a PR into `main`.
4. Include in the PR body
   - Summary of changes.
   - Motivation and context.
   - Tests run and results.
   - Known limitations or follow ups.

Humans typically review, merge, and delete branches.

---

## 4. Diff-first editing (preferred for assistants)

Assistants SHOULD avoid using `run_command` to embed large shell/Python
scripts to modify files. This is brittle because those scripts must be
embedded inside JSON strings and are easy to mis-escape.

Multi-line edits are routine. Use the diff-first helpers below to apply
them directly instead of treating them as tricky or deferring them to
humans.

Instead, assistants SHOULD use these tools:

- `build_unified_diff` – generate a unified diff from old/new file content.
- `build_section_based_diff` – generate a diff by describing section-level replacements, useful for large files.
- `apply_line_edits_and_commit` – small, line-targeted edits to existing files.
- `apply_patch_and_commit` – apply a unified diff (usually from the two diff builders above).
- `apply_text_update_and_commit` – full-file overwrite; use only when intentionally regenerating the entire file.
- `update_files_and_open_pr` – commit multiple files and open a PR in one call.

### 4.1 Tool selection for file edits

Use this table to choose the right tool path when editing files:

| Use case                      | Recommended tools                                                          |
|-------------------------------|----------------------------------------------------------------------------|
| Small/local edits             | `get_file_with_line_numbers` → `apply_line_edits_and_commit`             |
| Multi-line edits in large file| `get_file_with_line_numbers` → `build_section_based_diff` → `apply_patch_and_commit` |
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

1. `build_section_based_diff` to describe replacements by sections.
2. `apply_patch_and_commit` with the resulting patch.
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

1. `build_section_based_diff` to describe replacements by sections.
2. `apply_patch_and_commit` with the resulting patch.

`run_command` SHOULD be used primarily for:

- Tests (`pytest`, linters, type checkers).
- Small shell commands (`ls`, `grep`, diagnostics).
- NOT for large inline patch scripts.

---

## 5. Repository specific workflows

This section describes common workflows for this controller repo itself, `Proofgate-Revocations/chatgpt-mcp-github`.

### 5.1 Updating docs

1. Create a docs branch from `main` (for example `docs/update-handoff-and-workflows`).
2. Use `run_command` to inspect and edit `ASSISTANT_HANDOFF.md`, `docs/WORKFLOWS.md`, and related files.
3. Keep changes focused and incremental.
4. Run any documentation tooling or linters if present.
5. Use `commit_workspace` to commit changes to the docs branch.
6. Open a PR into `main` and summarize the doc changes clearly.

### 5.2 Medium sized file commits (token conscious)

When you want to test or exercise medium sized documentation or code commits without flooding the client with huge payloads:

1. Prefer branch scoped edits.
   - Create a feature or docs branch dedicated to the experiment.
2. Choose a medium sized target file (for example this file or `docs/ASSISTANT_HAPPY_PATHS.md`).
3. Make structured but modest edits.
   - Add or adjust a subsection.
   - Avoid rewriting the entire file unless that is the purpose of the change.
4. Use `apply_text_update_and_commit` or `apply_patch_and_commit` with:
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

## 7. Troubleshooting and stuck workflows

When a workflow stalls or fails repeatedly

1. Stop repeating the same failing tool call.
2. Summarize the errors and outputs you have seen.
3. Re read relevant docs and the controller contract.
4. Use `validate_tool_args` and `validate_environment` to rule out schema and configuration issues.
5. Check branch and issue state with `get_branch_summary` and `open_issue_context`.
6. Propose smaller, more observable next steps.
7. Ask the human for input when ambiguity remains.

Remember that this file is the engine side playbook. Personal controllers can adjust tone, verbosity, and other stylistic choices, but they should not contradict the safety and workflow rules documented here.

---

## 8. 1.0 proof-of-concept: exercised workflows

This section records concrete workflows exercised by an assistant against this controller to validate the 1.0 release. It is not a how-to; it is a "we actually did this" log.

### 8.1 Docs-only change using workspace + run_command + commit_workspace

Workflow:

1. Created branch `docs/workflow-poc-1-0b` from `main` using `ensure_branch`.
2. Created or refreshed a workspace for that branch using `ensure_workspace_clone`.
3. Ran `run_command` with:
   - `command`: `ls && ls docs && pytest -q`
   - `installing_dependencies`: `false`
   This validated that the workspace contained the repo files and that the test suite passes on this branch.
4. Fetched `docs/WORKFLOWS.md` for context using `get_file_contents` on the branch.
5. Used `apply_line_edits_and_commit` (documented in `docs/ASSISTANT_HAPPY_PATHS.md`) to append this section as a proof-of-concept log.
6. Opened a pull request from `docs/workflow-poc-1-0b` into `main` describing the exercised workflow and its purpose as a 1.0 proof-of-concept.

Notes:

- This flow demonstrates that:
  - Branch-first, docs-only changes work end-to-end.
  - `ensure_workspace_clone` + `run_command` is sufficient for running the full test suite.
  - `apply_line_edits_and_commit` can be used for low-token, direct-to-GitHub doc updates without rewriting the whole file.
- The PR associated with this workflow can be referenced as a concrete 1.0 validation artifact.
