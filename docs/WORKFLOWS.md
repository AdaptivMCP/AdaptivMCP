# Adaptiv Controller Workflows

This document describes **how to actually use** the Adaptiv Controller GitHub MCP server from ChatGPT at high power.

It is written for:

- People running an Adaptiv Controller–style GPT (for example "Joey’s GitHub").
- Advanced assistants that need precise, repeatable workflows over GitHub.
- Engineers who want to understand how to keep the controller safe while still moving quickly.

For internals and guarantees, see `docs/ARCHITECTURE_AND_SAFETY.md`.
For prompt / snapshot guidance, see `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md`.

---

## 1. Golden rules

All workflows should respect these rules, especially when touching the controller repo itself (`Proofgate-Revocations/chatgpt-mcp-github`).

1. **Never write directly to `main` for the controller repo.**
   - All work happens on feature branches (for example `issue-146-health-and-metrics-v4`, `fix-branch-default-main`, `docs-update-workflows`).
   - `main` is the canonical, production branch.

2. **Assume read-only until proven otherwise.**
   - The server may start with `WRITE_ALLOWED = False`.
   - You must not assume you can write; always check.

3. **Branch-first and pull-request-first.**
   - Create a feature branch before writing.
   - Make your changes on that branch and keep them reviewable.
   - Open a PR for any non-trivial change; Joey reviews, merges, and deletes branches.

4. **Verify every write.**
   - Rely on the built-in verification in `apply_text_update_and_commit`, `apply_patch_and_commit`, and `update_files_and_open_pr`.
   - Never assume a write succeeded without checking returned SHAs and file contents.

5. **Keep changes small and reviewable.**
   - Prefer multiple tight PRs over a single huge one.
   - Do not mix unrelated refactors, behavior changes, and docs in one PR.

6. **Use issues and PR descriptions as the source of truth.**
   - Every meaningful piece of work should have an issue and/or PR that a human can read without looking at code.

7. **Treat branch deletion as human-only.**
   - Assistants can create and use branches and open PRs.
   - Humans delete branches via GitHub UI/CLI, even though branch-delete tools exist.

---

## 2. Safe session bootstrap

At the start of a session, always establish a safe baseline. This is true for both humans and assistants and should be done in every new ChatGPT conversation before doing any real work.

### 2.1 Discover server policy and tools

1. Call **`get_server_config`**.
   - Inspect:
     - `write_allowed` – whether writes are currently permitted.
     - `approval_policy.write_actions` – whether writes are auto-approved or require explicit toggling.
     - `controller.repo` / `controller.default_branch` – which repo and branch the server considers canonical for itself.

2. Call **`list_all_actions`**.
   - Use this instead of hard-coding tool lists.
   - Confirm key tools exist (for example `apply_patch_and_commit`, `update_files_and_open_pr`, `run_tests`, `create_issue`).

3. Call **`controller_contract`**.
   - Provides a machine-readable contract between the controller prompt, assistants, and this server.
   - Treat this contract as authoritative; do not override or rephrase its expectations in your prompt. Keep it in sync with the published version instead of maintaining a separate copy or inventing a parallel "doc contract" in this repo.
   - Use it together with the docs on `main` instead of trying to memorize everything in your own words.

4. Optionally call **`validate_environment`**.
   - Useful for new deployments or when things look misconfigured.
   - Returns a structured report of environment checks (tokens, controller repo/branch, HTTP settings, etc.).

5. Optionally call **`validate_tool_args`** before invoking complex tools, especially write-tagged ones, to catch schema mismatches (missing required fields, extra fields, or type errors) before they become live failures.

### 2.2 Decide write posture

- If `write_allowed == False`:
  - Stay in **read-only mode** until the human explicitly asks for writes.
  - When they do, call `authorize_write_actions(approved=True)` and mention this in conversation.

- If `write_allowed == True`:
  - You are allowed to write, but must still:
    - Use feature branches.
    - Explain each destructive action.
    - Keep diffs clear and reviewable.

### 2.3 Confirm the repo and branch

For any workflow, be explicit about:

- `full_name` (for example `Proofgate-Revocations/chatgpt-mcp-github`).
- The branch you intend to use (for example `issue-146-health-and-metrics-v4`).

`_effective_ref_for_repo` (see `ARCHITECTURE_AND_SAFETY.md`) ensures:

- For the controller repo:
  - Missing or `main` refs resolve to `CONTROLLER_DEFAULT_BRANCH` (which defaults to `main` but can be pointed at a long-lived feature branch).
- For all other repos:
  - Missing refs default to `main`.

Even with this helper, you should **always** pass explicit `branch` / `ref` arguments when writing.

### 2.4 Confirm server version and docs

After connecting to this server in a new ChatGPT conversation, assistants **must**:

1. Confirm the server version:

   - Use `run_command` against this repo (or any environment that has the repo checked out) to run:

     ```bash
     python cli.py --version
     ```

   - Expect `1.0.0` for the 1.0 release.
   - If this does not match expectations (for example, docs mention a different version), stop and ask the human before proceeding.

2. Refresh docs from `main` for this repo:

   - Use `fetch_files` or `get_file_contents` on `main` to re-read at minimum:
     - `ASSISTANT_HANDOFF.md`.
     - `docs/WORKFLOWS.md`.
     - `docs/ARCHITECTURE_AND_SAFETY.md`.
     - `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md`.
     - `SELF_HOSTED_SETUP.md`.
   - Treat these docs on `main` as the **source of truth** for behavior. If the human says a PR was merged to update docs, assume those merged docs are correct even if a previous assistant said something different.

3. Align behavior with the controller contract and docs:

   - Use the controller contract plus these docs as your shared map of the system.
   - Do not rely on memory from previous chats; always believe `main` (code + docs + contract) when there is a conflict.

This section is intentionally redundant with the controller contract so that even if an assistant skips the contract tool, the workflows doc still forces them to check the version and re-read the docs after merges before doing serious work.

## 3. Inspecting a repository (read-only workflows)

Before proposing any write, build a mental model of the repo.

### 3.1 Basic layout

1. **List the tree**
   - Use `list_repository_tree` with a `path_prefix` such as:
     - `docs/` – documentation, setup guides, and workflows.
     - `src/` or `app/` – main application code.
     - `tests/` – tests to consult or extend.
   - Use pagination or limited depth if the repo is large.

2. **Read key files**
   - Use `get_file_contents` for small/medium files.
   - Use `get_file_slice` for large files (for example `main.py`):
     - Start with top ~200 lines for imports, globals, key helpers.
     - Jump to sections by line number if you already know where logic lives.

3. **Fetch multiple related files**
   - Use `fetch_files` when you know the exact paths (for example `main.py`, `docs/WORKFLOWS.md`, relevant tests).

### 3.2 Searching for patterns

Use `search` to:

- Find usages of specific helpers:
  - Example: `search("_effective_ref_for_repo")` within the controller repo.
- Discover patterns in your own org or across public GitHub:
  - Example: `search` for a particular FastAPI + MCP integration pattern.
- Locate tests or docs by keyword.

### 3.3 Inspecting issues and PRs

Use the issue/PR read tools (names may evolve, but typically include):

- `fetch_issue`, `fetch_issue_comments`.
- `fetch_pr`, `get_pr_diff`, `list_pull_requests`, `fetch_pr_comments`.
- `open_issue_context` to get a structured view of a given issue together with related branches and PRs.

Typical pattern:

1. Read the issue body and comments.
2. Attach to the right work using `open_issue_context` to discover the correct branch and/or PR.
3. Use this context to decide scope and expected behavior.

### 3.4 Read-only summary

When you finish inspection, summarize:

- Current behavior.
- Files and modules that will likely change.
- Whether tests/docs already exist for the target behavior.

Only then propose a concrete plan.

---

## 4. Branching strategy for assistants

### 4.1 Controller repo vs end-user repos

**Controller repo (`Proofgate-Revocations/chatgpt-mcp-github`)**

- `main` is canonical and must not be written to directly by the assistant.
- Workflows should:
  - Create a feature branch from `main` using `ensure_branch`.
  - Make all changes and run tests on that branch.
  - Open a PR from the feature branch back into `main`.
  - Let the human merge and delete the branch.

**End-user repos**

- Default behavior is simpler: missing refs default to `main`.
- You should still **strongly prefer** branch-first workflows:
  - Use `ensure_branch` to create branches like `feature/foo`, `bugfix/issue-123`, `docs/setup-guide`.
  - Only write to `main` via PR merges.

### 4.2 Recommended branch naming

These are recommendations, not enforced rules, but they help humans understand context:

- Issue-driven work: `issue-<number>-<slug>`
  - Example: `issue-146-health-and-metrics`.
- Bugfix or hotfix: `fix-<slug>`
  - Example: `fix-controller-default-branch-main`.
- Documentation: `docs-<area>`
  - Example: `docs-workflows-and-safety`.
- Experiment/spike: `spike-<slug>`.

Whatever you choose, always:

- Use a branch name that encodes **what** you are doing.
- Mention the branch in conversation and in PR descriptions.

### 4.3 Using `ensure_branch`

Typical sequence:

1. Decide base branch (usually `main`).
2. Decide feature branch name.
3. Call `ensure_branch` with:
   - `full_name`: repository.
   - `branch`: feature branch.
   - `from_ref`: base branch.
4. The tool will create the branch if it does not exist, or return the existing ref.

From that point on, **all** subsequent write tools for this work should use that feature branch.

---

## 5. Editing code and docs

You can use patch-based diffs or full-file updates, depending on what is safest and clearest for the change. The goal is to keep diffs reviewable, avoid accidental overwrites, and maintain a clean history.

### 5.1 When patch-based updates are a good fit

Use patch-oriented helpers such as `build_unified_diff`, `build_unified_diff_from_strings`, and `build_section_based_diff` when:

- You are changing a small, well-localized portion of a larger file (for example a single function or section in `main.py`).
- You want to minimize the risk of overwriting unrelated content.
- You want Joey (or future reviewers) to see a focused, easy-to-review diff.

After computing a diff, apply it with a write tool such as `apply_patch_and_commit`, following the controller's write policy.

### 5.2 When full-file updates are acceptable

Full-file updates (via tools like `apply_text_update_and_commit` or equivalent) are acceptable when:

- The file is relatively small (for example a new doc or a short module).
- You are performing a sweeping rewrite (for example restructuring a document or refactoring a small helper module).
- You can clearly see and control the entire file content in the workspace.

When using full-file updates:

- Make sure the new content fully reflects the desired final state of the file.
- Avoid mixing unrelated changes; keep the update focused.
- Run linters, formatters, and tests as appropriate.

### 5.3 Large files

For large files, such as `main.py`, prefer a combination of:

- `get_file_slice` to inspect specific regions.
- Patch helpers (`build_unified_diff`, `build_unified_diff_from_strings`, `build_section_based_diff`) to construct minimal, focused diffs.

This keeps token usage under control and avoids repetitive full-file replacements.

---

## 6. Workspace commands: tests and commands in a cloned repo

`run_command` and `run_tests` allow you to run real commands against a persistent checkout of a branch. Treat `run_command` like a real engineer's shell.

### 6.1 Running tests (`run_tests`)

Use this to gate changes before opening or merging a PR.

Typical pattern:

1. After making code changes on a feature branch, call `run_tests` with:
   - `full_name`.
   - `ref`: feature branch.
   - `test_command`: for example `pytest -q`.
   - `use_temp_venv`: usually `true` if the environment needs `pip install`.

2. Inspect the result:
   - `exit_code`.
   - `timed_out`.
   - `stdout`, `stderr`.
   - `stdout_truncated`, `stderr_truncated` flags.

3. Summarize failures (if any) and propose fixes.

4. Repeat: patch, commit, re-run tests until green.

### 6.2 Arbitrary commands (`run_command`)

Use this for:

- Linters (`ruff`, `flake8`, `mypy`, etc.).
- Code generators or migrations.
- One-off inspection scripts.

Guidelines:

- Always explain what you intend to run and why.
- Prefer running on a feature branch.
- Emphasize truncation when outputs are large.
- Avoid dangerous commands that could leak secrets; remember this is a user-owned environment.

---

## 7. Issues and PR lifecycle

The controller provides tools for issue and PR management. Use them to keep a clean audit trail.

### 7.1 Issues

Typical flow:

1. **Check for an existing issue**. Before calling `create_issue`, search for open issues that already describe the problem or feature. For example, use `search` against the repo with a query that includes key terms from the title/summary (or use any dedicated issue-listing tools exposed by the server). If you find a match, prefer updating or commenting on that issue instead of opening a new one.

2. **Create an issue** (only if one does not exist) using `create_issue`.
   - Title: concise problem statement.
   - Body: context, scope, constraints.

3. **Update the issue** over time:
   - Use `update_issue` to adjust scope or add checklists.
   - Use `comment_on_issue` for progress updates and decisions.

4. **Close the issue** when work is merged.

Best practices:

- Reference work in issue bodies and comments (branches, PRs, commits).
- Use checklists for multi-step work (for example tests, docs, rollout).

### 7.2 Pull requests

Use PR tools (`create_pull_request`, `merge_pull_request`, `close_pull_request`, `comment_on_pull_request`) to manage change flow.

Patterns:

- PR titles should be descriptive and often include the issue number:
  - Example: `Observability: health endpoint and metrics hooks (Fixes #146)`.

- PR bodies should include:
  - Motivation / problem statement.
  - Summary of changes.
  - Testing performed (`pytest -q`, manual testing, etc.).
  - Any risks or follow-ups.

- Comments should:
  - Record design decisions.
  - Link to additional context (issues, docs, discussions).

Humans typically own merging and branch deletion; assistants can prepare everything up to that point.

---

## 8. Example end-to-end workflows

This section gives concrete, high-usage patterns you can follow almost mechanically.

For any workflow that touches code or configuration, treat `run_tests` on the active feature branch and appropriate `run_command` invocations (formatters, linters, project scripts) as required steps before you open a PR, not optional extras.

### 8.1 Docs-only update (like this WORKFLOWS.md change)

1. **Bootstrap**
   - `get_server_config` → confirm write posture.
   - `list_all_actions` → confirm tools.

2. **Inspect**
   - Read `docs/WORKFLOWS.md` and any related docs.

3. **Branch**
   - `ensure_branch` from `main` to `docs-workflows-update`.

4. **Write**
   - Update `docs/WORKFLOWS.md` on the feature branch using patch-based edits or a focused full-file update, keeping the diff small and reviewable.

5. **(Optional) Tests**
   - Run `run_tests` with `pytest -q` on the branch to ensure nothing broke.

6. **PR**
   - Open a PR from `docs-workflows-update` to `main` with a clear summary.

### 8.2 Small code change + tests

1. Create a feature branch (for example `issue-123-fix-timeout-handling`).
2. Update code, tests, and docs using a mix of patch-based updates and focused full-file edits, choosing whichever is safest and clearest for the change.
3. Run `run_tests` on the branch.
4. Open a PR with:
   - Clear description.
   - `Fixes #123` in the body.
   - Testing summary.

### 8.3 Multi-file feature with docs and tests

1. Create an issue describing the feature.
2. Create a feature branch.
3. Update code, tests, and docs using patch-based and text-based tools.
4. Run `run_tests`.
5. Use `update_files_and_open_pr` or manual PR creation.
6. Iterate based on review.
7. Close the issue when merged.

---

## 9. Anti-patterns to avoid

To keep the controller safe and predictable, **avoid** the following:

1. **Full-file overwrites of large code modules without diffs.**
   - Do not use `apply_text_update_and_commit` on large, critical files like `main.py` when only a subset of lines should change.
   - Prefer patch-based flows or targeted full-file updates only when you can safely see and control the whole file.

2. **Implicit writes to `main`.**
   - Never rely on default branches for writes.
   - Always specify a feature branch and confirm it in conversation.

3. **Mixing unrelated changes.**
   - Do not combine metrics changes, refactors, docs, and unrelated bug fixes in one PR.
   - Keep each PR focused so diffs and failures are easy to reason about.

4. **Running heavy commands without explanation.**
   - Avoid `run_command` or `run_tests` without explaining what will run and why.
   - Be especially careful with commands that install dependencies or modify the environment.

5. **Ignoring truncation flags.**
   - When `stdout_truncated` or `stderr_truncated` is true, mention that you only saw part of the output.

6. **Assuming write access forever.**
   - `WRITE_ALLOWED` can change during a session.
   - Be prepared for write tools to fail with authorization errors and respond by explaining the situation to the user.

---

## 10. Using this document

Use this document as the **operational playbook** for Adaptiv Controller workflows:

- When in doubt, follow the patterns here.
- When you add new tools or orchestrations, update this doc to include new workflows.
- Keep `WORKFLOWS.md`, `ARCHITECTURE_AND_SAFETY.md`, and `ASSISTANT_DOCS_AND_SNAPSHOTS.md` in sync so humans and assistants share the same mental model.


## 11. Large-file edits and section-based orchestration

For very large files (like main.py) assistants should avoid sending the entire file back and forth. Instead, use the section-based diff tools built into this controller.

Recommended pattern:

1. Use `get_file_slice` to inspect only the relevant region of a large file.
2. Decide the exact line ranges that need to change.
3. Prepare a `sections` payload: each section has `start_line`, `end_line`, and `new_text`.
4. Call `build_section_based_diff` with `full_name`, `path`, `ref`, and `sections`.
5. Take the returned `patch` and pass it to `apply_patch_and_commit` on the same branch.
6. Re-read the updated region (via `get_file_slice`) and summarize the change.

Notes:

- `start_line` and `end_line` are 1-based and inclusive.
- You can insert without deleting by using a section where `end_line == start_line - 1`.
- Sections must not overlap and must be passed in ascending order by `start_line`.

### Using `validate_json_string` for strict JSON flows

When you construct JSON payloads in a prompt or tool call, you can use the `validate_json_string` tool before sending them back to a client or saving them in docs.

Typical flow:

1. Build the JSON string you intend to return.
2. Call `validate_json_string` with that raw string.
3. If `valid` is true, use `normalized` as the canonical JSON you return to clients or feed into other tools so whitespace
   differences cannot reintroduce parse errors.
4. If `valid` is false, fix the error reported by `error` and try again.

---

## 12. PR creation smoke test for truncation and branch flow

When you suspect problems with PR creation (for example, 422 errors or truncated titles/bodies), you can run a simple smoke test that mirrors the way this controller is used in practice:

1. Create a throwaway docs branch (for example `docs-pr-flow-smoke-test`) from `main` using `ensure_branch`.
2. Add a small markdown file under `docs/` (for example `docs/pr-flow-test-adaptiv-pr-check.md`) using `apply_text_update_and_commit` or a patch-based flow. Include a reasonably long but readable summary in the file so there is something meaningful to describe in the PR body.
3. Open a PR back into `main` using `create_pull_request` with:
   - A long, descriptive title (for example `Test PR: validate Adaptiv Controller PR flow and truncation handling`).
   - A multi-paragraph body that lists the steps being validated (branch creation, commit on the feature branch, PR creation, and truncation behavior).
4. Inspect the resulting PR in GitHub and confirm:
   - The title is intact (not truncated unexpectedly).
   - The full body is present, including the final sentences of the description).
   - The `head` and `base` branches are correct and match the feature and `main` branches you expect.
5. After you finish debugging, merge or close the smoke-test PR and delete the branch in the GitHub UI to keep the repository clean.

This pattern doubles as both a diagnostics workflow and an example of how assistants should exercise PR flows using the controller itself without touching production code paths.

## 13. Troubleshooting when you feel stuck or in a loop

When a workflow feels stuck, confusing, or at risk of looping, use this checklist instead of repeatedly calling the same tools with the same arguments:

1. **Stop repeating failing tool calls.**
   - Do not keep calling the same tool with identical arguments after it fails.
   - Summarize what happened, including error messages and any truncated output flags.

2. **Re-read the contract and docs.**
   - Re-run `controller_contract` and re-open the relevant sections of `ASSISTANT_HANDOFF.md` and this `WORKFLOWS.md` file.
   - Check whether you are violating any expectations (for example branch usage, write posture, or JSON discipline).

3. **Validate arguments and JSON.**
   - Use `validate_tool_args` for complex or write-tagged tools to confirm that your arguments match the schema.
   - Use `validate_json_string` for any complex JSON payloads you intend to return or pass between tools.

4. **Check the environment.**
   - If failures look environmental (permissions, tokens, repo state), call `validate_environment` and summarize any warnings or errors.

5. **Inspect recent changes and branch state.**
   - Use `get_branch_summary` on the active feature branch to understand ahead/behind state, PR status, and last-known tests or workflow runs.
   - If working off an issue, use `open_issue_context` to confirm you are on the correct branch/PR for that issue.

6. **Scale back the next step.**
   - Propose a smaller, more observable action (for example fetching a single file slice or running a narrow test command) instead of a broad, multi-step tool sequence.

7. **Ask the human for guidance.**
   - If the situation is still ambiguous after these steps, summarize what you tried, what failed, and what you think is happening, then ask the human which direction to take next instead of continuing to guess.

These steps are meant to keep assistants from silently spinning in loops and to surface problems (contract mismatches, environment issues, schema drift) quickly so humans can intervene when needed.
