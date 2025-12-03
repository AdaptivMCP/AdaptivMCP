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

Instead, assistants SHOULD use these tools:

- `build_unified_diff` – generate a unified diff from old/new file content.
- `build_section_based_diff` – generate a diff by describing section-level
  replacements, useful for large files.
- `apply_text_update_and_commit` – commit full updated file content.
- `apply_patch_and_commit` – commit a unified diff.
- `update_files_and_open_pr` – commit multiple files and open a PR in one call.

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

### 5.2 Updating the controller contract

1. Create a dedicated branch for contract changes.
2. Update the contract source and related docs.
3. Ensure that version numbers and compatibility notes are updated.
4. Run tests and schema validation as appropriate.
5. Open a PR and flag it as a contract change.

### 5.3 Adjusting server configuration or defaults

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
