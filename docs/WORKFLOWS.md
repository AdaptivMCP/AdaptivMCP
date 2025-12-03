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
   - Never assume a write succeeded without checking returned SHAs and file contents.

5. Keep changes small and reviewable.
   - Prefer several focused PRs over one huge one.
   - Avoid mixing unrelated refactors, behavior changes, and docs in a single PR.

6. Use issues and PR descriptions as the human source of truth.
   - Every meaningful piece of work should have an issue and or PR that a human can read without reading code.

7. Treat branch deletion as human only.
   - Assistants can create branches and open PRs.
   - Humans delete branches with the GitHub user interface or command line.

8. Remember the separation of concerns.
   - This document is the engine playbook and should stay stable.
   - Your personal controller prompts are where you change style and preferences. Do not try to encode personal preferences by forking the engine when a prompt change would do.

---

## 2. Safe session bootstrap

At the start of a session, always establish a safe baseline. Do this in every new ChatGPT conversation before doing real work.

### 2.1 Discover server policy and tools

1. Call `get_server_config`.
   - Inspect write posture and approval policy.
   - Note the configured controller repository and default branch.

2. Call `list_all_actions`.
   - Use this instead of hard coding tool lists.
   - Confirm that key tools exist, such as patch builders, write helpers, and workspace tools.

3. Call `controller_contract`.
   - Treat the contract as the single authoritative description of expectations between the controller and this server.
   - Use it together with docs on the main branch.

4. Optionally call `validate_environment`.
   - Especially helpful for new deployments or when things look misconfigured.

5. For complex or write tagged tools, optionally call `validate_tool_args` before live use to catch schema mismatches early.

### 2.2 Decide write posture

- If write actions are not allowed
  - Stay in read only mode until the human explicitly asks for writes.
  - When they do, call `authorize_write_actions` with approval set to true and mention this in conversation.

- If write actions are allowed
  - You may write, but must still
    - Use feature branches rather than main.
    - Explain destructive actions.
    - Keep diffs clear and reviewable.

### 2.3 Confirm repository and branch

Be explicit about

- The repository name, such as `Proofgate-Revocations/chatgpt-mcp-github`.
- The branch you plan to use, such as `docs-workflows-update` or an issue branch.

Use explicit branch or ref arguments for all writes, even though the server has sensible defaults.

### 2.4 Confirm server version and docs

When connecting to this server in a new ChatGPT conversation, assistants should

1. Confirm the server version, for example by running a small version command via `run_command` in a workspace.
2. Refresh docs from the main branch by reading at least
   - `ASSISTANT_HANDOFF.md`.
   - `docs/WORKFLOWS.md`.
   - `docs/ARCHITECTURE_AND_SAFETY.md`.
   - `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md`.
   - `docs/SELF_HOSTED_SETUP.md`.
3. Align behavior with the controller contract and current docs rather than with any stale memory from previous chats.

---

## 3. Inspecting a repository

Before proposing a write, build a mental model of the repository.

### 3.1 Basic layout

1. List the tree
   - Use `list_repository_tree` with a path prefix, such as
     - `docs/` for documentation and workflows.
     - `src/` or `app/` for application code.
     - `tests/` for tests.

2. Read key files
   - Use `get_file_contents` for small and medium files.
   - Use `get_file_slice` for large files, such as `main.py`.

3. Fetch multiple related files
   - Use `fetch_files` when you know the exact paths, such as `main.py`, workflow docs, and relevant tests.

### 3.2 Search for patterns

Use `search` to

- Find usages of specific helpers or functions.
- Discover patterns in your own organization or across public GitHub.
- Locate tests or docs by keyword.

### 3.3 Inspect issues and pull requests

Use the issue and pull request tools to

- Read issue bodies and comments.
- Read pull request descriptions, diffs, and discussion.
- Use `open_issue_context` to get a structured view of related branches and pull requests for a given issue.

### 3.4 Read only summary

After inspection, summarize

- Current behavior.
- Files and modules that are likely to change.
- Existing tests and docs that cover the target behavior.

Only then propose a plan.

---

## 4. Branching strategy

### 4.1 Controller repo versus end user repos

Controller repo, `Proofgate-Revocations/chatgpt-mcp-github`

- Main is canonical and must not be written to directly by assistants.
- Workflows should
  - Create a feature branch from main using `ensure_branch`.
  - Make all changes and run tests on that branch.
  - Open a pull request back into main.
  - Let a human merge and delete the branch.

End user repositories

- Defaults are simpler, but branch first workflows are still recommended.
- Use `ensure_branch` to create branches like `feature/foo`, `bugfix/issue-123`, or `docs/setup-guide`.

### 4.2 Recommended branch naming

These names are suggestions that make histories easier to read

- Issue driven work, `issue-number-short-slug`.
- Bugfix or hotfix, `fix-short-slug`.
- Docs, `docs-area`.
- Experiments, `spike-short-slug`.

Whatever pattern you use, always mention the branch name in conversation and in pull request descriptions.

### 4.3 Using `ensure_branch`

Typical sequence

1. Choose the base branch, usually main.
2. Choose a feature branch name.
3. Call `ensure_branch` with repository, branch, and base ref.
4. Use that branch for all write tools in the workflow.

---

## 5. Editing code and docs

You can use patch based diffs or full file updates, depending on what is safest and clearest. The goal is to keep diffs reviewable, avoid accidental overwrites, and maintain a clean history.

### 5.1 Patch based updates

Use patch oriented helpers when

- You are changing a small, localized part of a larger file.
- You want reviewers to see tight, focused diffs.

After computing a diff, apply it with `apply_patch_and_commit` or related helpers, following the write policy.

### 5.2 Full file updates

Full file updates are acceptable when

- The file is small, such as a short module or doc file.
- You are intentionally rewriting the entire file and have clear control of the final content.

When using full file updates, keep the change focused and run tests or formatters as appropriate.

### 5.3 Large files

For large files such as `main.py`, prefer

- `get_file_slice` to inspect specific regions.
- Patch helpers for minimal diffs.

---

## 6. Workspace commands

`run_command` and `run_tests` let you run real commands against a persistent checkout of a branch. Treat `run_command` as a shell you access through the controller.

### 6.1 Running tests

Use `run_tests` to gate changes before opening or merging a pull request. Typical pattern

1. After making code changes on a feature branch, call `run_tests` with repository, branch, and test command.
2. Inspect exit code, output, and truncation flags.
3. Summarize failures and propose fixes when needed.
4. Repeat patch, commit, and test until green.

### 6.2 Arbitrary commands

Use `run_command` for

- Linters and formatters.
- Code generators and migrations.
- One off inspection scripts.

Always explain what you plan to run and why, and prefer running on feature branches.

---

## 7. Issues and pull requests

The controller exposes tools for managing issues and pull requests. Use them to keep a clear audit trail that both humans and assistants can follow.

### 7.1 Issues

A simple workflow

1. Before creating a new issue, search for an existing one that matches the problem or idea.
2. If none exists, use `create_issue` with a concise title and a body that explains context and scope.
3. Use `update_issue` and `comment_on_issue` to keep the issue aligned with the plan.
4. Close the issue when work is merged.

### 7.2 Pull requests

Use pull request tools to drive change flow

- Titles should be descriptive and often reference issue numbers.
- Bodies should explain motivation, list changes, describe tests, and note risks or follow ups.
- Comments should record decisions and link to relevant docs or issues.

Assistants prepare branches and pull requests. Humans typically merge and delete branches.

---

## 8. Example workflows

This section sketches common end to end workflows that you can follow almost mechanically. Adjust details through your personal controller prompts as needed.

### 8.1 Docs only update

1. Bootstrap with `get_server_config` and `list_all_actions`.
2. Inspect relevant docs.
3. Create a docs branch from main with `ensure_branch`.
4. Update docs on that branch with patch or full file helpers.
5. Optionally run tests.
6. Open a pull request with a clear description.

### 8.2 Small code change with tests

1. Create a feature branch named after the issue or change.
2. Update code, tests, and docs with appropriate tools.
3. Run `run_tests`.
4. Open a pull request referencing the issue.

### 8.3 Multi file feature with docs and tests

1. Open or update an issue that describes the feature.
2. Create a feature branch.
3. Update code, tests, and docs.
4. Run tests and relevant commands.
5. Open a pull request and iterate with review.
6. Close the issue when merged.

---

## 9. Large file edits and JSON helpers

For very large files, avoid shuttling entire contents back and forth. Instead use section based diffs.

Recommended pattern

1. Use `get_file_slice` to inspect only the relevant region.
2. Decide exact line ranges that must change.
3. Prepare a `sections` payload for `build_section_based_diff`.
4. Apply the returned patch with `apply_patch_and_commit`.
5. Re read the updated region and summarize the change.

When constructing JSON payloads, use `validate_json_string` before returning or using them in other tools. Use the normalized value from that tool to avoid subtle formatting issues.

---

## 10. Troubleshooting and personal controllers

When a workflow feels stuck, confusing, or at risk of looping

1. Stop repeating failing tool calls.
2. Summarize errors, outputs, and truncation flags.
3. Re read the controller contract and relevant docs, especially this file and the assistant docs.
4. Use `validate_tool_args` and `validate_environment` to rule out schema and configuration problems.
5. Use `get_branch_summary` and `open_issue_context` to understand branch and issue state.
6. Propose a smaller, more observable next step.
7. Ask the human for direction if ambiguity remains.

Finally, remember that this file describes the engine side patterns. If you want your personal controller to behave differently in tone, verbosity, or workflow preference, change your ChatGPT controller prompt rather than trying to work around the engine. The engine should stay conservative and predictable so that your controller can be as adaptive and personal as you like on top of it.
