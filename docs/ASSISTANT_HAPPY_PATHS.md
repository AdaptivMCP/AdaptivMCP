# Assistant happy paths playbook

This document is a **playbook for assistants** (such as Joeys GitHub) using the Adaptiv Controller GitHub MCP server.

It does **not** describe every tool in detail. Instead, it provides concrete, repeatable **happy paths**
for the most common workflows. If you are doing X, follow the matching
section below.

If you ever find yourself guessing or improvising a new flow, check this file
first. If there is no good happy path, *that* is a signal to add or improve
one (in a docs branch, via PR).

---

## 1. Bootstrapping a session with this server

**Goal:** Understand server configuration, write gating, and controller defaults before doing anything else.

**When to use:** At the start of a session, or any time you are unsure about write permissions or defaults.

**Steps:**
1. Call `get_server_config` to learn:
   - Whether `write_allowed_default` is true or false for this controller repo.
   - The configured controller repository and default branch.
   - HTTP and timeout limits that might affect large operations.
2. Call `controller_contract` to refresh your mental model of:
   - Expected workflows for assistants.
   - Which tools are intended for discovery, safety, execution, diffs, and large files.
3. If you plan to make any GitHub state changes (commits, branches, PRs, issue updates), plan to:
   - Call `authorize_write_actions` before the first write-capable tool.
   - Use branch-first flows instead of writing to `main` directly.

**Validation:**
- You can see `write_allowed` in `get_server_config` and confirm that write tools are either allowed by default or gated.
- After `authorize_write_actions`, write-capable tools stop returning gating errors.

---

## 2. Read-only repo orientation

**Goal:** Get oriented in the controller repo without changing anything.

**When to use:** Any time you need to understand structure, key docs, or high-level behavior before editing.

**Steps:**
1. Use `get_repo_defaults` (or `get_server_config.controller.repo`) to confirm the `full_name` and default branch.
2. Call `list_repository_tree` with:
   - `full_name` set to the controller repo.
   - `ref` set to the default branch (usually `main`).
   - Optionally, a `path_prefix` such as `docs/`, `tests/`, or `src/` to narrow the view.
3. For specific files:
   - Use `get_file_contents` for small to medium files.
   - Use `get_file_slice` when you only need a portion of a large file (for example, a single section in `main.py` or a long test file).
4. When you need to search:
   - Prefer `search_code_in_repo` with a repo-scoped query (for example, a function name, test name, or filename).
   - Avoid unqualified global GitHub search unless the user explicitly wants cross-repo context.

**Validation:**
- You successfully retrieved and summarized the docs or code files you needed without triggering any write tools.
- Tree listings reflect the expected layout (docs, tests, main code, workflows).

---

## 3. Small documentation change in this repo

**Goal:** Update a single documentation file (like this one) on a dedicated branch and open a PR.

**When to use:** For focused text-only changes to one file.

**Steps:**
1. Planning:
   - Identify the target file path (for example `docs/ASSISTANT_HAPPY_PATHS.md`).
   - Read current content with `get_file_contents` (or `get_file_slice` for very large docs).
2. Ensure you are on a docs branch:
   - Call `ensure_branch` with a new branch name (for example `docs/assistant-happy-paths-playbook`) and `from_ref` set to the default branch.
3. Enable writes (if needed):
   - Call `authorize_write_actions` once for the session when you are ready to commit.
4. Prepare the updated content:
   - Draft the new version of the file in your response.
   - If the file is large or only a section is changing, consider using `build_section_based_diff` instead of a full replacement.
5. Commit the change using one of:
   - `apply_text_update_and_commit` for full-file replacement, or
   - `apply_patch_and_commit` with a unified diff from `build_unified_diff`, or
   - `update_file_sections_and_commit` when you have clear section markers.
   In all cases, set `branch` to your docs branch and provide a descriptive commit message.
6. Open a pull request:
   - Use `open_pr_for_existing_branch` with:
     - `branch` set to your docs branch.
     - `base` left default or set to `main` (the MCP server normalizes this to the configured default).
     - A clear `title` and `body` summarizing the doc change.
7. Optionally list the PR to confirm state:
   - Call `list_pull_requests` or `list_repository_pull_requests` filtered by head branch.

**Validation:**
- `apply_text_update_and_commit` or similar returns `status` equal to `committed` with a verification block.
- `open_pr_for_existing_branch` returns an open PR with the expected branch and base.
- `list_repository_pull_requests` shows the new PR in the open list.

---

## 4. Single-file code change with tests

**Goal:** Make a focused change to one code file, add or update tests, run the test suite, then open a PR.

**When to use:** Small behavior change or bugfix that mostly touches one module plus its tests.

**Steps:**
1. Discovery:
   - Use `search_code_in_repo` and `list_repository_tree` to locate the main implementation file and its tests (for example, `tests/test_apply_text_update_and_commit.py`).
   - Fetch the relevant files using `get_file_contents` or `get_file_slice`.
2. Plan the change:
   - Draft the code change and any test updates in your reasoning.
   - Keep the change set small and focused on one feature or bug.
3. Create a feature branch:
   - Call `ensure_branch` with `branch` set to a new feature name (for example `feat/single-file-update-happy-path`).
4. Enable writes:
   - Call `authorize_write_actions` if not already done in this session.
5. Apply code changes in the repo:
   - For small files: use `build_unified_diff` with your proposed new content and then `apply_patch_and_commit`, or use `apply_text_update_and_commit` directly.
   - For large or sectioned files: use `build_section_based_diff` and then `apply_patch_and_commit`.
   - Update both implementation and tests in the same branch, with clear commit messages.
6. Run tests in a workspace:
   - Call `ensure_workspace_clone` for the repo and branch.
   - Use `run_tests` pointing at the branch, with `test_command` (for example `pytest`).
   - If tests require dependencies, set `installing_dependencies=true` on the first run that installs packages.
7. Handle failures:
   - If tests fail, use `run_command` (for example `pytest path/to/test -k failing_case -vv`) to iterate until passing.
   - Update code and tests via patch-based tools, commit again, and re-run tests.
8. Open a PR:
   - Use `open_pr_for_existing_branch` targeting `main`.
   - In the PR body, summarize behavior changes and explicitly mention tests run (for example `pytest` passing on the feature branch via `run_tests`).

**Validation:**
- The last `run_tests` call returns a successful outcome.
- All code and test file commits show as part of a single PR on the feature branch.

---

## 5. Multi-file documentation update using a single call

**Goal:** Update multiple small documentation files together and open one PR with a single high-level tool call.

**When to use:** When you have several related doc edits (for example updating `README.md`, `ASSISTANT_HANDOFF.md`, and files in `docs/`).

**Steps:**
1. Discovery:
   - Use `list_repository_tree` with `path_prefix` set to `docs/` and `README.md`, `ASSISTANT_HANDOFF.md`, etc.
   - Fetch current contents via `fetch_files`.
2. Plan edits:
   - Draft updated content for each file in your reasoning.
   - Keep each edit self-contained and clearly described.
3. Create a branch:
   - Call `ensure_branch` with a descriptive branch name (for example `docs/multi-file-cleanup`).
4. Enable writes if needed:
   - Call `authorize_write_actions`.
5. Use `update_files_and_open_pr` with:
   - `full_name` set to the controller repo.
   - `title` summarizing the docs changes.
   - `files` as a list where each entry includes at least: path, branch, and updated content (following the tool schema).
   - `base_branch` set to the default branch.
   - `new_branch` set to your docs branch if you want the tool to create and push it; otherwise rely on `ensure_branch`.
6. Review the response:
   - Confirm each file updated has `status` committed.
   - Confirm the created PR details (number, URL, base, head).

**Validation:**
- All target files show updated content in the PR diff.
- The PR body and title match the described multi-file change.

---

## 6. Large-file or partial-section edits

**Goal:** Safely edit a small part of a large file without loading or rewriting the entire file.

**When to use:** When dealing with long modules, config files, or docs where only a section needs changing.

**Steps:**
1. Identify the region:
   - Use `get_file_slice` to retrieve only the lines relevant to the change.
   - Optionally, use `search_code_in_repo` to find line ranges or markers.
2. Plan the patch:
   - Decide whether to use `build_section_based_diff` (preferred for line-based sections) or `build_unified_diff` (when you already have full original/updated content for the region).
3. Build the diff:
   - Call `build_section_based_diff` with: `full_name`, `path`, `sections`, and `ref` set to the branch you are editing.
   - Verify the returned diff looks correct and only touches the intended lines.
4. Apply and commit:
   - Use `apply_patch_and_commit` with the diff for that file and your branch.
5. Optionally run tests or linters via `run_tests` or `run_command` if the change affects behavior.

**Validation:**
- The diff returned by `apply_patch_and_commit` matches the intended section edits.
- No unrelated parts of the large file were changed.

---

## 7. Workspace-first flows (local-style editing)

**Goal:** Use a persistent workspace clone for more complex or iterative work, then commit changes back.

**When to use:** For larger refactors, running formatters, or any workflow that benefits from running multiple shell commands.

**Steps:**
1. Create or refresh a workspace:
   - Call `ensure_workspace_clone` with `ref` set to your feature branch (or `main` if you are just exploring).
2. Explore and modify in the workspace:
   - Use `run_command` with commands like `ls`, `tree`, or `grep` to understand the layout.
   - Run formatters or generators (for example `ruff`, `black`, or project-specific scripts) as needed.
   - Keep `installing_dependencies` false unless the command installs packages.
3. Run tests:
   - Call `run_tests` for full suite runs or use `run_command` with more targeted test invocations.
4. Commit workspace changes:
   - Use `commit_workspace` when you want to commit all changes in one commit, or
   - Use `commit_workspace_files` to commit a specific subset of files.
   - Ensure `ref` matches your feature branch.
5. Open or update a PR:
   - Open a new PR using `open_pr_for_existing_branch`, or
   - Let `update_files_and_open_pr` manage both updates and PR creation if that tool fits the current flow.

**Validation:**
- Workspace commands see the expected files and changes.
- Commits made via `commit_workspace` or `commit_workspace_files` appear in the remote branch.

---

## 8. Working with issues and PR context

**Goal:** Use GitHub issues and pull requests as structured context, and update them as part of a workflow.

**When to use:** When the user references an existing issue/PR, or you want to open/update one as part of your work.

**Steps:**
1. Read context:
   - Use `open_issue_context` to load an issue along with related branches and pull requests.
   - Use `fetch_issue` and `fetch_issue_comments` for direct issue details and discussion.
   - Use `fetch_pr`, `fetch_pr_comments`, and `list_pr_changed_filenames` to understand a PR and its diff.
2. Summarize before acting:
   - Summarize the current state of the issue or PR for the user.
   - Highlight linked branches, tests mentioned, and any follow-up tasks.
3. Update issues or PRs:
   - Use `comment_on_issue` or `comment_on_pull_request` to add summaries or progress updates.
   - Use `update_issue` to adjust title, body, labels, or assignees as requested.
4. React to review signals:
   - Use `get_pr_reactions` or `get_issue_comment_reactions` when you need to understand feedback patterns (for example thumbs up on a comment).
5. Lifecycle management:
   - For finished work, use `merge_pull_request` if the user asks to merge, respecting branch protections and CI status.
   - Use `close_pull_request` when explicitly asked to close without merging.

**Validation:**
- Issue or PR comments you post appear in subsequent fetches.
- Issue state and labels reflect requested changes.
- PR merge or close actions show the expected status in `fetch_pr`.

---

## 9. CI and workflow runs

**Goal:** Inspect and react to GitHub Actions workflows related to a branch or PR.

**When to use:** When the user asks about CI status, failing jobs, or workflow history.

**Steps:**
1. List workflows and runs:
   - Use `list_workflow_runs` for the repo, optionally filtering by `branch` or `status`.
2. Inspect a specific run:
   - Call `get_workflow_run` with a `run_id` to see its conclusion, status, and timing.
   - Use `list_workflow_run_jobs` to see individual jobs in that run.
3. Debug failures:
   - For failing jobs, use `get_job_logs` to retrieve logs.
   - Summarize root causes and surfaces relevant log snippets (without overloading the user).
4. Trigger workflows when appropriate:
   - Use `trigger_workflow_dispatch` to run a workflow on a specific ref when the user asks.
   - Optionally, use `trigger_and_wait_for_workflow` for a synchronous happy path where you summarize the outcome.

**Validation:**
- Workflow run details match what GitHub shows for the branch/PR.
- Logs you summarize align with the reported failures or success.

---

## 10. Background reads for expensive operations

**Goal:** Offload long-running or potentially slow read operations to background jobs while you continue reasoning.

**When to use:** When fetching large sets of files or expensive searches via `fetch_files`, `list_repository_tree`, or similar tools tagged as read actions.

**Steps:**
1. Start a background job:
   - Call `start_background_read` with the underlying read tool and arguments (for example, a large `fetch_files` batch).
2. Poll for completion:
   - Use `get_background_read` with `job_id` until it reports completion and optionally returns the result.
   - Or use `list_background_reads` to see all tracked jobs and their statuses.
3. Use results once ready:
   - When a job completes, use its result to continue your workflow (for example summarizing many files or building a diff).

**Validation:**
- The `start_background_read` response returns a valid `job_id`.
- `get_background_read` transitions from pending to completed, and the embedded result matches what a direct read call would have returned.

---

## 11. General guidance for staying on the happy path

- Prefer repo-scoped search and controller-specific tools over global GitHub searches.
- Use branch-first workflows for any change to this controller repo.
- Keep changes small, focused, and backed by tests when behavior changes.
- Use large-file helpers (`get_file_slice`, `build_section_based_diff`, `build_unified_diff_from_strings`) instead of loading huge files.
- Use `validate_json_string` and `validate_tool_args` when emitting structured payloads for other tools or controllers.
- After docs in this repo are updated and merged into the default branch, treat them as the **source of truth** for future sessions and re-read them via `get_file_contents` or `fetch_files`.
