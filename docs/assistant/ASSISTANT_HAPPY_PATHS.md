# Assistant happy paths playbook

This document is a **playbook for assistants** (such as Joeys GitHub) using the Adaptiv Controller GitHub MCP server. It is not the contract itself. `controller_contract` is the single, authoritative contract between controllers, assistants, and this server; this playbook provides concrete, repeatable **happy paths** that illustrate how to honor that contract in common workflows. If there is ever a conflict, `controller_contract` wins and this file must be updated via docs PRs.

If you ever find yourself guessing or improvising a new flow, check this file and `controller_contract` together first. If there is no good happy path, *that* is a signal to add or improve one (in a docs branch, via PR) so that the docs stay aligned with the contract.

---

## 1. Bootstrapping a session with this server

**Goal:** Understand server configuration, write gating, and controller defaults before doing anything else.

**When to use:** At the start of a session, or any time you are unsure about write permissions or defaults.

**Steps:**
1. Call `get_server_config` and `validate_environment` to learn:
   - Whether `write_allowed` is currently true for this server instance.
   - HTTP, timeout, and concurrency limits that might affect large operations.
   - That the server is healthy before proceeding.
2. Call `list_write_tools` so you know which tools are gated before you attempt them.
3. Call `controller_contract` to refresh your mental model of:
   - The configured controller repository and its `default_branch`.
   - Whether writes are enabled by default for that controller repo (`write_allowed_default`).
   - Expected workflows for assistants and which tools are intended for discovery, safety, execution, diffs, and large files.
4. Call `list_all_actions` (include_parameters=true). This server guarantees each tool exposes a non-null `input_schema` in that listing, synthesizing a minimal object schema when none is published. Before you invoke any MCP tool in this session (including tools you think you already understand), call `describe_tool` for that tool and, when applicable, use `validate_tool_args` on your planned `args` object before the first real invocation—especially for write-capable or complex tools. When you need metadata or validation for multiple tools, prefer a single `describe_tool` or `validate_tool_args` call with up to 10 tools at once instead of many separate calls. Treat this as mandatory, not optional.5. Once you know the controller `default_branch`, immediately create or ensure a dedicated feature branch for this task with `ensure_branch` (or `create_branch`), and run discovery tools like `get_repo_dashboard`, `list_repository_tree`, and `get_latest_branch_status` against that feature branch instead of the real default branch. Do not run MCP tools directly against `main`.
6. If you plan to make any GitHub state changes (commits, branches, PRs, issue updates), plan your write posture:
   - For writes that touch the controller default branch or unscoped write tools, call `authorize_write_actions` before using them so `_ensure_write_allowed` will accept the operation.
   - For commits to feature branches, prefer branch-scoped tools like `commit_workspace`, `commit_workspace_files`, and patch-based helpers. These tools pass a `target_ref` and are allowed even when `write_allowed` is `False`, while the controller default branch remains protected behind the write gate.
7. When you need to understand branch state or CI health, call `get_latest_branch_status` for the feature branch you care about (and the base, typically `main`) instead of guessing from old workflow logs. Use that to decide whether a failure is tied to the current HEAD or an older commit.

**Validation:**
- You can see `write_allowed` in `get_server_config` and confirm that write tools are either allowed by default or gated.
- After `authorize_write_actions`, write-capable tools stop returning gating errors.
- `get_latest_branch_status` shows ahead/behind information, PR status, and the most recent workflow run for the current branch HEAD, so you do not retry fixes for already-merged commits.
---

## 2. Read-only repo orientation

**Goal:** Get oriented in the controller repo without changing anything.

**When to use:** Any time you need to understand structure, key docs, or high-level behavior before editing.

**Steps:**
1. Use `get_repo_defaults` to confirm the controller `full_name` and its default branch.
2. Ensure you are working from a feature branch created from the default branch via `ensure_branch` (or `create_branch`), and avoid using MCP tools that target the real default branch (for example `main`) while doing work.
3. Call `list_repository_tree` with:
   - `full_name` set to the controller repo.
   - `ref` set to your feature branch.
   - Optionally, a `path_prefix` such as `docs/`, `tests/`, or `src/` to narrow the view.
4. For specific files:
   - Use `get_file_contents` for small to medium files.
   - Use `get_file_slice` when you only need a portion of a large file (for example, a single section in `main.py` or a long test file).
5. When you need to search within this repo:
   - Prefer the GitHub search tool (for example `search` with a `code` query) using a repo-scoped query (function name, test name, or filename) rather than a global search.
   - Avoid unqualified global GitHub search unless the user explicitly wants cross-repo context.
3. For specific files:
   - Use `get_file_contents` for small to medium files.
   - Use `get_file_slice` when you only need a portion of a large file (for example, a single section in `main.py` or a long test file).
4. When you need to search within this repo:
   - Prefer the GitHub search tool (for example `search` with a code query) using a repo-scoped query (function name, test name, or filename) rather than a global search.
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
   - First, call `build_pr_summary` with the repo `full_name`, your docs branch `ref`, a concise human-written `title`/`body`, and (optionally) a short `changed_files` summary and any `tests_status` or `lint_status` strings if checks were run.
   - Then, use `open_pr_for_existing_branch` with:
     - `branch` set to your docs branch.
     - `base` left default or set to `main` (the MCP server normalizes this to the configured default).
     - The `title` and `body` rendered from the `build_pr_summary` result so PR descriptions stay consistent with the contract.
7. Optionally list the PR to confirm state:
   - Call `list_pull_requests` filtered by head branch to confirm the new PR exists and is open.
7. Optionally list the PR to confirm state:
   - Call `list_pull_requests` filtered by head branch to confirm the new PR exists and is open.

**Validation:**
- `apply_text_update_and_commit` or similar returns `status` equal to `committed` with a verification block.
- `open_pr_for_existing_branch` returns an open PR with the expected branch and base.
- `list_pull_requests` shows the new PR in the open list.
---

## 4. Single-file code change with tests

**Goal:** Make a focused change to one code file, add or update tests, run the test suite, then open a PR.

**When to use:** Small behavior change or bugfix that mostly touches one module plus its tests.

**Steps:**
1. Discovery:
   - Use repo-scoped search (for example the `search` tool with a `code` query) and `list_repository_tree` to locate the main implementation file and its tests (for example, `tests/test_apply_text_update_and_commit.py`).
   - Fetch the relevant files using `get_file_contents` or `get_file_slice`.2. Plan the change:
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
6. Run tests and lint in a workspace:
   - Call `ensure_workspace_clone` for the repo and branch to create or refresh a workspace before running tests or linters.
   - Use `run_quality_suite` for full-suite or default quality gate runs, `run_lint_suite` for lint/static analysis, or `run_tests` / `run_command` for more targeted invocations.
   - If tests or linters require dependencies, set `installing_dependencies=true` on the first run that installs packages and use `run_command` inside the workspace to install what is needed instead of editing project config only to satisfy local runs.
7. Handle failures and refresh the workspace after each commit:
   - When tests or linters fail, you are responsible for fixing them. Use `run_command` (for example `pytest path/to/test -k failing_case -vv` or `ruff check path/to/module.py`) together with small, focused code and test edits until everything passes.
   - After using `commit_workspace` or `commit_workspace_files` to push changes from a workspace, treat that workspace as stale for validation. Before running `run_tests`, `run_lint_suite`, `run_quality_suite`, or any other forward-moving action, call `ensure_workspace_clone` again with `ref` set to the same feature branch and `reset=true`, then continue from that fresh clone.
8. Open a PR:
   - Use `build_pr_summary` first with the controller repo `full_name`, your feature `ref`, a short title/body, and a summary of `changed_files`, `tests_status`, and `lint_status` based on the most recent runs.
   - Then call `open_pr_for_existing_branch` targeting `main`, passing the `title` and `body` from `build_pr_summary`. In the PR, explicitly mention which tests and lint suites you ran and that they passed on the feature branch.

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

## 6. Large-file or partial-section edits (line-based)

**Goal:** Safely edit a small part of a large file without loading or rewriting the entire file, using minimal line-based payloads.

**When to use:** When dealing with long modules, config files, or docs where only a section needs changing and you know the relevant line ranges.

**Steps:**
1. Identify the region:
   - Use `get_file_slice` to retrieve only the lines relevant to the change.
   - When you need a compact, numbered view to point at exact lines, use `get_file_with_line_numbers`.
   - Optionally, use a repo-scoped code search (for example via the `search` tool) to find line ranges or markers before slicing.2. Choose an edit strategy:
   - For marker- or section-based edits, you can still use `build_section_based_diff` + `apply_patch_and_commit`.
   - For direct, minimal line edits where line numbers are known, use `apply_line_edits_and_commit`.
3. Using `apply_line_edits_and_commit` for line-based edits:
   - Call `apply_line_edits_and_commit` with:
     - `full_name`: controller repo (for example `Proofgate-Revocations/chatgpt-mcp-github`).
     - `path`: file you are editing (for example `docs/ASSISTANT_HAPPY_PATHS.md`).
     - `branch`: feature/docs branch (never `main` directly).
     - `message`: clear commit message.
     - `sections`: list of edits, each with:
       - `start_line`: 1-based inclusive start line.
       - `end_line`: 1-based inclusive end line (or equal to `start_line` for a single-line replace).
       - `new_text`: new text for that range (may span multiple lines).
   - The server fetches the base file from GitHub, applies the line edits in memory, and commits via the Contents API.
   - Set `include_diff=false` (the default) to keep responses small; set it to `true` only when you explicitly need a diff.
4. Line-selection checklist to avoid duplicates and misplaced inserts:
   - Always re-read a slightly larger slice than the exact range you plan to edit (5–10 lines of context before and after) so
     you can see if the old text needs to be removed rather than appended.
   - When replacing code, set `start_line`/`end_line` to cover the *existing* lines you are removing; do not add the new text as
     a separate section unless both ranges must coexist.
   - For multi-block edits, list the sections in file order and sanity-check that no two ranges overlap or leave the old block
     intact.
5. Optionally run tests or linters via `run_quality_suite`, `run_lint_suite`, `run_tests`, or `run_command` if the change affects behavior.
- `apply_line_edits_and_commit` returns `status` equal to `committed` with commit metadata.
- If you set `include_diff=true`, the diff touches only the intended lines and no unrelated parts of the file.

---

## 7. Workspace-centered flows (local-style editing)

**Goal:** Use a persistent workspace clone for more complex or iterative work, then commit changes back.

**When to use:** For larger refactors, running formatters, or any workflow that benefits from running multiple shell commands.

**Steps:**
1. Create or refresh a workspace:
   - Call `ensure_workspace_clone` with `ref` set to your feature branch (or `main` if you are just exploring).
2. Explore and modify in the workspace:
   - Use `run_command` with commands like `ls`, `tree`, or `grep` to understand the layout.
   - Run formatters or generators (for example `ruff`, `black`, or project-specific scripts) as needed.
   - Keep `installing_dependencies` false unless the command installs packages. When dependencies are required for tests or linters, install them via `run_command` in the workspace environment rather than editing project config solely to satisfy one-off runs.
3. Run tests and lint from a fresh clone after commits:
   - Before running `run_quality_suite`, `run_lint_suite`, `run_tests`, or other test commands, ensure you are working from a fresh workspace clone for the current feature branch. After you commit via `commit_workspace` or `commit_workspace_files`, call `ensure_workspace_clone` again with `ref` set to that branch and `reset=true` before continuing.
   - Use `run_quality_suite` for the default quality gate, `run_lint_suite` for lint/static analysis, or `run_tests` / `run_command` with targeted invocations as needed.
   - Treat any failing tests or lint checks as your responsibility to fix; iterate with small edits and re-runs until they pass.
4. Commit from the workspace:
   - Use `commit_workspace` when you want to commit all changes in one commit, or
   - Use `commit_workspace_files` to commit a specific subset of files.
   - Ensure `ref` matches your feature branch.
5. Open or update a PR:
   - Use `build_pr_summary` to construct a structured PR summary for the current branch, including a succinct title, body, list of changed areas, and the latest tests/lint status.
   - Open a new PR using `open_pr_for_existing_branch` and render the `title` and `body` from `build_pr_summary`, or
   - Let `update_files_and_open_pr` manage both updates and PR creation if that tool fits the current flow, still using `build_pr_summary` to shape the description.
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

1. Read context:
   - Use `open_issue_context` to load an issue along with related branches and pull requests.
   - Use `get_issue_overview` when you want a normalized summary of the issue, checklists parsed from the body and comments, and candidate branches/PRs before acting.
   - Use `fetch_issue` and `fetch_issue_comments` for direct issue details and discussion.
   - Use `get_pr_overview` when you want a compact PR summary (metadata, changed files, and CI status) before touching any write tools.
   - Use `recent_prs_for_branch` when you know a branch name and want to discover open (and optionally closed) pull requests whose head matches that branch.
   - Use `fetch_pr`, `fetch_pr_comments`, and `list_pr_changed_filenames` to understand a PR and its diff in more detail when needed.
2. Summarize before acting:
   - Summarize the current state of the issue or PR for the user.
   - Highlight linked branches, tests mentioned, and any follow-up tasks.
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

## 10. Handling expensive read operations safely

**Goal:** Keep large or potentially slow read operations predictable while avoiding timeouts and unnecessary data transfer.

**When to use:** When fetching large sets of files or performing broad repository scans via `fetch_files`, `list_repository_tree`, or similar tools tagged as read actions.

**Steps:**
1. Narrow the scope before reading:
   - Use `list_repository_tree` with a `path_prefix` (for example `docs/` or `src/github_mcp/`) instead of listing the entire repo.
   - Prefer repo-scoped search queries (via the `search` tool) to locate candidate files before fetching content.
2. Fetch only what you need:
   - Use `get_file_contents` for small files.
   - Use `get_file_slice` when you only need a specific region of a large file (for example a single function or section).
   - For multiple files, use `fetch_files` with a focused list of paths rather than the entire tree.
3. Summarize and discard:
   - After reading, summarize key findings in your own reasoning and avoid repeatedly re-fetching the same large content in a single session.

**Validation:**
- Read tools complete without hitting configured timeouts from `get_server_config`.
- You only fetch the slices and files needed for the current task, not the entire repository or huge unused regions.
---

## 11. General guidance for staying on the happy path

- Prefer repo-scoped search and controller-specific tools over global GitHub searches.
- Use feature branches and pull requests for any change to this controller repo.
- Keep changes small, focused, and backed by tests when behavior changes.
- Use large-file helpers (`get_file_slice`, `build_section_based_diff`, `build_unified_diff_from_strings`) instead of loading huge files.
- Use `describe_tool` to fetch the input schema for a specific tool before constructing or repairing arguments, then `validate_tool_args` to check your payloads. When a tool call fails with a schema or argument error, stop guessing, re-read the tool definition via `list_all_actions`/`describe_tool`, and fix the payload to match the declared schema before trying again.
- Treat `run_command` as your interactive terminal for short, focused commands (tests, `grep`, formatters, simple utilities), and rely on diff- and section-based tools (`update_file_sections_and_commit`, `apply_line_edits_and_commit`, `build_section_based_diff`, `apply_patch_and_commit`) for multi-line or structural edits instead of embedding large scripts inside tool arguments.
- After docs in this repo are updated and merged into the default branch, treat them as the **source of truth** for future sessions and re-read them via `get_file_contents` or `fetch_files`.

---

## 12. PR review and revision loop

**Goal:** Review an existing pull request like a human would, then iterate on code or docs in response to feedback.

**When to use:** The user references an open PR, asks for a review summary, or wants you to push follow-up commits to the same branch.

**Steps:**
1. Load PR context:
   - Use `fetch_pr` for title, body, base/head, and status.
   - Call `list_pr_changed_filenames` for the file list and `fetch_pr_comments` for discussion threads.
2. Summarize before editing:
   - Capture the problem statement, proposed fix, and any blocking review comments.
   - Note whether CI is passing by checking the PR status in `fetch_pr` or via workflow runs (Section 9).
3. If edits are required on the PR branch:
   - Use `ensure_branch` on the head branch from `fetch_pr.head.ref`.
   - Fetch relevant files (`get_file_contents`, `get_file_slice`) and plan small, targeted changes.
   - Apply changes with `apply_patch_and_commit`, `apply_text_update_and_commit`, or `commit_workspace_files` if you worked locally.
4. Run validation the reviewer will expect:
   - Use `run_tests` or targeted `run_command` invocations (for example `pytest -k <name>`) on the PR branch.
5. Communicate back on the PR:
   - Post a concise summary with `comment_on_pull_request`, linking to tests you ran and which comments are resolved.
   - If you addressed a specific thread, reply in that thread via `comment_on_pull_request` with `in_reply_to` pointing at the comment ID.

**Validation:**
- New commits appear on the PR branch and show up in `fetch_pr`.
- Your PR comment reflects the latest state and references the tests you ran.
- CI status moves from failing to passing or at least shows progress toward green.

---

## 13. Keeping feature branches fresh and resolving conflicts

**Goal:** Refresh a feature branch against the default branch (or PR base) and resolve merge conflicts predictably.

**When to use:** The PR shows "out of date" or merge conflicts, or the user asks to rebase/merge the branch onto the latest base.

**Steps:**
1. Inspect the branch state:
   - Use `fetch_pr` (if a PR exists) to see base/head and whether the branch is behind.
   - Otherwise, call `get_repo_defaults` for the default branch and confirm the target base.
2. Prepare a workspace for conflict resolution:
   - Call `ensure_workspace_clone` with `ref` set to the feature branch.
   - Run `run_command` with `git fetch origin` followed by `git merge origin/<base>` (or `git rebase origin/<base>` if rebase is desired).
3. Resolve conflicts locally:
   - Use `run_command` to inspect conflicted files with commands like `sed -n`, `rg`, or other CLI tools.
   - After fixing conflicts, run `git status` and `git add` via `run_command` to stage changes.
4. Verify behavior:
   - Run `run_tests` or targeted commands to ensure the conflict resolution did not break functionality.
5. Commit and push:
   - Use `commit_workspace` (or `commit_workspace_files` for a subset) with a message like "Merge <base> into <branch>".
   - Confirm the branch is updated by re-running `fetch_pr` and checking that GitHub no longer reports the branch as behind or conflicted.
**Validation:**
- `run_command` for `git status` shows a clean working tree after the merge/rebase.
- Tests pass on the refreshed branch.
- The PR no longer shows merge conflicts or "out of date" warnings.

---

## 14. Hotfixes and backports to release branches

**Goal:** Apply a targeted fix to a release branch (for example `release/*` or `stable/*`) and open a PR against that branch rather than `main`.

**When to use:** Security fixes, regression patches, or backports that must ship on an older line while mainline work continues.

**Steps:**
1. Identify the correct base:
   - Use `list_repository_tree` or `get_repo_defaults` to confirm release branch names.
   - If a PR triggered the request, read its body for target branches.
2. Create a backport branch:
   - Call `ensure_branch` with `from_ref` set to the release branch (for example `release/1.2`) and a head like `backport/<issue-id>`.
3. Implement the minimal fix:
   - Fetch only the files needed with `get_file_slice`/`get_file_contents`.
   - Apply the change using the same single-file or line-edit tools described in Sections 4 and 6.
4. Validate against release constraints:
   - Run `run_tests` focusing on the release branch's expectations; avoid pulling in unrelated features.
5. Open a PR targeting the release branch:
   - Use `open_pr_for_existing_branch` with `base` set to the release branch and a PR body that references the original issue/PR.

**Validation:**
- The PR shows the release branch as `base` and the backport branch as `head`.
- Tests or checks relevant to the release branch pass.
- Scope of the diff is limited to the hotfix, with no forward-port features mixed in.

---

## 15. Repository hygiene: labels, milestones, and triage

**Goal:** Keep issues and PRs organized using labels, milestones, and checklists while mirroring how human maintainers triage.

**When to use:** Triage new issues, categorize incoming PRs, or update metadata after status changes.

**Steps:**
1. Read the current state:
   - Use `fetch_issue`/`fetch_pr` for title, body, and existing labels or milestones.
   - Call `fetch_issue_comments` or `fetch_pr_comments` to understand prior triage decisions.
2. Apply or adjust labels and milestones:
   - Use `update_issue` to add or replace labels, assignees, and milestones as requested.
   - When closing an item, include a short summary comment via `comment_on_issue`/`comment_on_pull_request`.
3. Track follow-ups:
   - Add checklists or next steps in the issue body (via `update_issue`) so humans can see progress at a glance.
   - If work is split across PRs, cross-link them in comments and the PR body.
4. Confirm visibility:
   - Re-fetch the issue or PR to ensure labels and milestones are set as expected.

**Validation:**
- Updated labels/milestones appear in subsequent `fetch_issue`/`fetch_pr` calls.
- Comments clearly summarize state changes for human collaborators.
- Closed items have an explicit resolution note rather than silent closure.

---

## 16. Contributing to non-controller repositories (fork-style flow)

**Goal:** Work on repositories other than this controller as if you were contributing via a fork, staying explicit about branch selection and write permissions.

**When to use:** The user asks for changes in an external repo, or the controller is configured with a different `controller.repo` than the repo you need to edit.

**Steps:**
1. Identify the target repo and branch:
   - Call `get_repo_defaults` for the target repo to learn its default branch.
   - Explicitly set `full_name` on every tool invocation to avoid defaulting back to the controller repo.
2. Create a topic branch:
   - Use `ensure_branch` with `full_name` set to the target repo and `from_ref` set to its default branch.
   - Keep branch names descriptive (for example `feat/<short-summary>` or `bugfix/<issue-id>`).
3. Apply changes using the same commit tools as in Sections 3–6, always passing `full_name` and the topic branch.
4. Run validation commands in a workspace clone of that repo:
   - Call `ensure_workspace_clone` with `full_name` and the topic branch.
   - Use `run_tests`/`run_command` as needed.
5. Open a PR against the target repo:
   - Use `open_pr_for_existing_branch`, setting `full_name` and `base` explicitly.
   - In the PR body, note any controller-specific constraints (for example limited token scopes).

**Validation:**
- Commits land on the correct repo/branch and appear in `fetch_pr` for that repo.
- Tests run against the intended codebase rather than the controller repo.
- PR metadata clearly shows the external repo and branch pair to avoid accidental controller edits.

