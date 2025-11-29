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

3. **Use branch-first, patch-first, PR-first.**
   - Create a feature branch before writing.
   - Use patch-based edits (`build_unified_diff` + `apply_patch_and_commit`) for code.
   - Open a PR for any non-trivial change.

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

At the start of a session, always establish a safe baseline.

### 2.1 Discover server policy and tools

1. Call **`get_server_config`**.
   - Inspect:
     - `write_allowed` – whether writes are currently permitted.
     - `approval_policy.write_actions` – whether writes are auto-approved or require explicit toggling.
     - `controller.repo` / `controller.default_branch` – which repo and branch the server considers canonical for itself.

2. Call **`list_all_actions`**.
   - Use this instead of hard-coding tool lists.
   - Confirm key tools exist (for example `apply_patch_and_commit`, `update_files_and_open_pr`, `run_tests`, `create_issue`).

3. Optionally call **`validate_environment`**.
   - Useful for new deployments or when things look misconfigured.
   - Returns a structured report of environment checks (tokens, controller repo/branch, HTTP settings, etc.).

### 2.2 Decide write posture

- If `write_allowed == False`:
  - Stay in **read-only mode** until the human explicitly asks for writes.
  - When they do, call `authorize_write_actions(approved=True)` and mention this in conversation.

- If `write_allowed == True`:
  - You are allowed to write, but must still:
    - Use feature branches.
    - Explain each destructive action.
    - Prefer patch-based flows with clear diffs.

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

---

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

Typical pattern:

1. Read the issue body and comments.
2. Open any referenced PRs.
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

## 5. Single-file text edits (docs and small configs)

Use `apply_text_update_and_commit` when you are replacing or creating a single file and a full-text representation is easier to reason about than a patch.

### 5.1 When this is appropriate

- New docs (for example adding `docs/NEW_FEATURE.md`).
- Small config files.
- Medium-sized docs where the entire file is under control and easy for a human to review in one diff.

Avoid using it for:

- Very large code files.
- Shared modules with many unrelated call sites where localized patches are safer.

### 5.2 Workflow

1. **Read the file (if it exists)**
   - Use `get_file_contents` to capture the current state.

2. **Draft the new content**
   - Prepare the full file content in ChatGPT, including headers, sections, and examples.
   - Show the proposed file to the user.

3. **Apply the update**
   - Call `apply_text_update_and_commit` with:
     - `full_name`: repo.
     - `path`: file path (for example `docs/WORKFLOWS.md`).
     - `branch`: feature branch (for example `update-workflows-doc`).
     - `updated_content`: full new file text.
     - Optional `message`: concise commit message (for example `Update workflows doc for controller usage`).

4. **Review the result**
   - Inspect the returned diff and SHA.
   - Optionally re-read the file with `get_file_contents` from the feature branch.

5. **Repeat for related docs**
   - If other docs need updates (for example `SELF_HOSTED_SETUP`, `ASSISTANT_DOCS_AND_SNAPSHOTS`), repeat this process.

---

## 6. Patch-based edits (recommended default for code)

For most code changes, prefer patch-based workflows:

### 6.1 Why patches

- Diffs are localized and easy to review.
- The patch application will fail if the original file changes unexpectedly, preventing accidental full-file overwrites.
- Tests in this repo assume patch-based flows for critical modules like `main.py`.

### 6.2 Workflow using `build_unified_diff` + `apply_patch_and_commit`

1. **Read the baseline**
   - Use `get_file_contents` (or `get_file_slice` for large files) on the feature branch.

2. **Propose the change**
   - Describe in natural language **and** show the intended code blocks.
   - Keep the change focused (for example "instrument `mcp_tool` with metrics" not "also refactor a bunch of unrelated helpers").

3. **Generate a unified diff**
   - Compute `new_content` by applying your changes to the baseline.
   - Call `build_unified_diff` with:
     - `full_name`, `path`, `ref` (feature branch), `new_content`.
     - Optional `context_lines` (default is usually fine).
   - Inspect the returned diff:
     - Confirm only the intended lines changed.
     - Check no unrelated sections are touched.

4. **Apply the patch**
   - Call `apply_patch_and_commit` with:
     - `full_name`, `path`, `branch` (same feature branch).
     - `patch`: the exact diff returned by `build_unified_diff`.
     - `message`: precise commit message.
   - Let the tool perform verification (read-after-write + SHA comparison).

5. **Re-read and sanity-check**
   - Optionally re-fetch the file.
   - Confirm imports, globals, and function signatures are consistent.

6. **Repeat** for additional files (tests, helpers, etc.), keeping each commit coherent.

---

## 7. Multi-file changes and PR orchestration

When a change spans multiple files (for example code + tests + docs), use higher-level orchestration.

### 7.1 `update_files_and_open_pr`

This tool is ideal when you:

- Know all the files that will change.
- Have final versions of each file content.
- Want to create a feature branch, commit each file, and open a PR in one flow.

Typical sequence:

1. **Prepare updated contents for each file**
   - For each path, draft the updated content.
   - Optionally host large contents at a temporary URL if supported by the tool.

2. **Call `update_files_and_open_pr`** with:
   - `full_name`.
   - `base_branch` (for example `main`).
   - `feature_branch` (for example `issue-146-health-and-metrics-v4`).
   - File updates list (paths + contents/URLs).
   - PR metadata:
     - `title`.
     - `body` (including references like `Fixes #146`).
     - `draft` flag (useful when tests or review are still in progress).

3. **Inspect results**
   - Verify that each file was committed and verified.
   - Review the PR URL.

4. **Iterate via normal GitHub review**
   - Humans review, comment, and ultimately merge.
   - Assistant can respond to feedback by updating the branch.

### 7.2 Manual PR flows

For smaller or more iterative work you may:

1. Use `ensure_branch`.
2. Apply one or more changes via `apply_text_update_and_commit` / `apply_patch_and_commit`.
3. Call `create_pull_request` directly with:
   - `head`: feature branch.
   - `base`: main.
   - `title`, `body`.

This is closer to how a human works with `git` and GitHub UI.

---

## 8. Workspace commands: tests and commands in a cloned repo

`run_command` and `run_tests` allow you to run real commands against a temporary checkout of a branch.

### 8.1 Running tests (`run_tests`)

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

### 8.2 Arbitrary commands (`run_command`)

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

## 9. Issues and PR lifecycle

The controller provides tools for issue and PR management. Use them to keep a clean audit trail.

### 9.1 Issues

Typical flow:

1. **Create an issue** (if one does not exist) using `create_issue`.
   - Title: concise problem statement.
   - Body: context, scope, constraints.

2. **Update the issue** over time:
   - Use `update_issue` to adjust scope or add checklists.
   - Use `comment_on_issue` for progress updates and decisions.

3. **Close the issue** when work is merged.

Best practices:

- Reference work in issue bodies and comments (branches, PRs, commits).
- Use checklists for multi-step work (for example tests, docs, rollout).

### 9.2 Pull requests

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

## 10. Example end-to-end workflows

This section gives concrete, high-usage patterns you can follow almost mechanically.

### 10.1 Docs-only update (like this WORKFLOWS.md change)

1. **Bootstrap**
   - `get_server_config` → confirm write posture.
   - `list_all_actions` → confirm tools.

2. **Inspect**
   - Read `docs/WORKFLOWS.md` and any related docs.

3. **Branch**
   - `ensure_branch` from `main` to `docs-workflows-update`.

4. **Draft**
   - Propose a full new version of `docs/WORKFLOWS.md` in conversation.

5. **Write**
   - Use `apply_text_update_and_commit` on `docs/WORKFLOWS.md` in the feature branch.

6. **(Optional) Tests**
   - Run `run_tests` with `pytest -q` on the branch to ensure nothing broke.

7. **PR**
   - Open a PR from `docs-workflows-update` to `main` with a clear summary.

### 10.2 Small code change + tests

1. Inspect the relevant code and tests.
2. Create a feature branch (for example `issue-123-fix-timeout-handling`).
3. Use `build_unified_diff` + `apply_patch_and_commit` for a focused change.
4. Add or update tests using the same patch-based flow.
5. Run `run_tests` on the branch.
6. Open a PR with:
   - Clear description.
   - `Fixes #123` in the body.
   - Testing summary.

### 10.3 Multi-file feature with docs and tests

1. Create an issue describing the feature.
2. Create a feature branch.
3. Update code, tests, and docs using patch-based and text-based tools.
4. Run `run_tests`.
5. Use `update_files_and_open_pr` or manual PR creation.
6. Iterate based on review.
7. Close the issue when merged.

---

## 11. Anti-patterns to avoid

To keep the controller safe and predictable, **avoid** the following:

1. **Full-file overwrites of large code modules without diffs.**
   - Do not use `apply_text_update_and_commit` on large, critical files like `main.py` when only a subset of lines should change.
   - Always prefer patch-based flows so humans can see exactly what changed.

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

## 12. Using this document

Use this document as the **operational playbook** for Adaptiv Controller workflows:

- When in doubt, follow the patterns here.
- When you add new tools or orchestrations, update this doc to include new workflows.
- Keep `WORKFLOWS.md`, `ARCHITECTURE_AND_SAFETY.md`, and `ASSISTANT_DOCS_AND_SNAPSHOTS.md` in sync so humans and assistants share the same mental model.

If you adhere to these workflows, the Adaptiv Controller will behave like a very disciplined senior engineer: branch-first, patch-first, test-first, and always ready to explain what it is about to do and why.