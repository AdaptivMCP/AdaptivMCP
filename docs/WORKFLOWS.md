# Adaptiv Controller Workflows

This document describes recommended workflows for using the Adaptiv Controller (Joey’s GitHub MCP server) inside ChatGPT. It is written for advanced users and assistants who want to drive safe, repeatable GitHub workflows via the MCP tools exposed by this repository.

The examples assume this repository is deployed as a self-hosted MCP server and wired into ChatGPT as a custom controller (for example "Joey’s GitHub").

---

## 1. Core principles

All workflows in this controller should follow a few simple rules:

1. **Never write directly to `main` for the controller repo.**
   - Use feature branches or dedicated smoke-test branches.
2. **Prefer patch-based edits for non-trivial changes.**
   - Generate diffs with `build_unified_diff`, apply them with `apply_patch_and_commit`.
3. **Verify every write.**
   - Use the built-in verification in `apply_text_update_and_commit`, `apply_patch_and_commit`, and `update_files_and_open_pr`.
4. **Keep changes small and reviewable.**
   - Group related edits into a single PR.
   - Avoid mixing large refactors with unrelated behavior changes.
5. **Use issues to track work.**
   - Open, update, and close GitHub issues so humans always have a high-level summary.

---

## 2. Inspecting a repository

When first connecting to a repo, assistants should use read tools to build context before proposing any writes. Typical sequence:

1. **List the tree**
   - Use `list_repository_tree` with a `path_prefix` (for example `docs/`, `src/`, `tests/`) to understand layout.
2. **Read files incrementally**
   - Use `get_file_slice` for large files (like `main.py`) to avoid pulling everything at once.
   - Use `get_file_contents` or `fetch_files` for smaller files or multiple related files.
3. **Search for patterns**
   - Use `search` to find usages, patterns, and examples in the repo or across public GitHub.
   - Example: "find usages of _effective_ref_for_repo" or "search public repos for a specific integration pattern".
4. **Inspect issues and PRs**
   - Use the issue/PR read tools (fetch_issue, fetch_pr, get_pr_diff, etc.) to understand ongoing work.

Guidance for assistants:

- Always start in read-only mode.
- Summarize what you found, then propose a plan that includes which files and branches you will touch.

---

## 3. Branching strategy for assistants

For the controller repo (`Proofgate-Revocations/chatgpt-mcp-github`):

- The server enforces controller-aware ref scoping:
  - For this repo, missing or `main` refs are remapped to the configured controller default branch by `_effective_ref_for_repo`.
- Assistants should still explicitly choose a branch name that describes the work.

Recommended pattern:

- For refactor or feature work: `ally-<feature>-<short-description>`
- For testing experimental flows: `smoke/<short-description>`

Workflow:

1. Use `ensure_branch` to create a feature branch from a base branch (usually `main` or the refactor branch).
2. Perform changes and commits only on the feature branch.
3. Use `update_files_and_open_pr` or branch-specific edit flows to open a PR back into the base branch.

For end-user repos (not the controller repo):

- Default ref behavior is simpler: missing refs fall back to `main`.
- Encourage users to adopt a branch-first model (for example "never commit directly to main from the controller").

---

## 4. Single-file text edits with verification

Use `apply_text_update_and_commit` when you want to replace the contents of a single file with updated text (including creating new files).

Typical workflow:

1. Read the current file with `get_file_contents` (or note that it does not exist yet).
2. Propose the full updated contents to the user.
3. When approved:
   - Call `apply_text_update_and_commit` with:
     - `full_name`: repo name.
     - `path`: file path.
     - `branch`: feature branch.
     - `updated_content`: full new file content.
     - Optional `message`: commit message.
4. Let the tool handle commit + verification.
5. Optionally show the returned diff to the user.

When to use this:

- Creating new docs or config files.
- Rewriting relatively small files where a full-text replacement is easier to reason about than a patch.

When **not** to use this:

- Large source files where preserving surrounding context is important. Prefer patch-based flows there.

---

## 5. Patch-based edits (recommended default)

For most code changes, the recommended pattern is:

1. Read the file with `get_file_contents`.
2. Propose a patch in natural language or with inline code blocks.
3. Once the user approves, generate a unified diff via `build_unified_diff` by providing:
   - `full_name`, `path`, `ref`, `new_content`.
   - `context_lines` (usually 3).
4. Inspect the diff returned by `build_unified_diff` and show it to the user for sign-off.
5. Apply the patch using `apply_patch_and_commit` with:
   - `full_name`, `path`, `branch`, `patch`, `message`.
6. Rely on the tool’s verification to confirm the commit and updated file contents.

Benefits:

- Changes are localized and easy to review.
- The diff clearly shows exactly what changed.
- Patch application fails fast if the underlying file has changed unexpectedly (preventing accidental overwrites).

---

## 6. Multi-file edits and PRs

When touching multiple files, use `update_files_and_open_pr` to keep everything in a single, coherent PR.

Workflow:

1. For each file you want to update, generate updated contents (inline or from a temporary URL).
2. Call `update_files_and_open_pr` with:
   - `full_name`, `base_branch`, `feature_branch`.
   - A list of file updates (paths + content or content URLs).
   - PR metadata (title, body, labels, draft flag as appropriate).
3. The tool will:
   - Ensure the branch exists from the base.
   - Commit each file, verifying after each commit.
   - Open a PR only if all commits and verifications succeed.

Assistant guidance:

- Use this when multiple files must stay in sync (for example code + tests + docs).
- Keep PRs scoped to a single logical change.
- Reference any related issues in the PR description (for example "Fixes #130").

---

## 7. Workspace commands: run_command and run_tests

Use workspace tools when changes need to be validated by real commands in a cloned repo.

### 7.1 Running tests

1. After applying changes on a feature branch, call `run_tests` with:
   - `full_name`: repo.
   - `ref`: the feature branch.
   - `test_command`: for example `pytest -q`.
   - `use_temp_venv`: `true` when you may need to install dependencies.
2. Examine the result:
   - `exit_code`, `timed_out` flags.
   - `stdout`, `stderr`, plus `stdout_truncated` / `stderr_truncated`.
3. Summarize failures back to the user and propose fixes if tests fail.

### 7.2 Running arbitrary commands

Use `run_command` for tasks like:

- Running type checkers or linters.
- Running migration commands.
- Building assets or running one-off scripts.

Assistant guidance:

- Always explain what you intend to run and why.
- Prefer running commands on feature branches.
- Respect truncation flags: if output is truncated, mention that your view is partial.

---

## 8. Issues and lifecycle management

Use the issue tools (`create_issue`, `update_issue`, `comment_on_issue`) to keep a human-readable log of what is happening.

Typical pattern:

1. **Create an issue** describing the work you plan to do.
2. **Update the issue body** as the plan evolves or as scope changes.
3. **Comment** with status updates as you complete concrete steps (tests added, docs written, PR merged).
4. **Close the issue** when the work is complete and merged.

Best practices for assistants:

- Reference issue numbers in PR titles or descriptions (for example "Docs: workflows and assistant docs (Fixes #130)").
- Avoid splitting a single logical change across multiple unrelated issues.
- Use checklists in issue bodies when there are multiple steps.

---

## 9. Example end-to-end workflow

Here is a high-level example of how an assistant might implement and ship a feature using the Adaptiv Controller tools:

1. **Understand the request**
   - Read the relevant issue(s).
   - Inspect code and docs using `list_repository_tree`, `get_file_contents`, and `get_file_slice`.

2. **Plan the work**
   - Propose which files will change and how.
   - Decide on a feature branch name and confirm with the user.

3. **Create and prepare the branch**
   - Use `ensure_branch` to create the feature branch from the base (for example `main` or a refactor branch).

4. **Make code and doc changes**
   - For small or new files, use `apply_text_update_and_commit`.
   - For existing code, use `build_unified_diff` + `apply_patch_and_commit`.
   - Keep commits focused and well-labeled.

5. **Run tests**
   - Use `run_tests` on the feature branch.
   - Summarize any failures and iterate until tests pass.

6. **Open a PR**
   - Use `update_files_and_open_pr` if multiple files were changed, or direct branch/PR helpers if you have already committed.
   - Reference relevant issues (for example `Fixes #130`).

7. **Finalize and merge**
   - After human review and approval, use PR helpers to merge or close the PR as appropriate.
   - Update and close related issues.

8. **Reflect and update docs**
   - If the workflow or tools changed, update the relevant docs so future assistants have an accurate picture.

By following these patterns, assistants and operators can build reliable, repeatable workflows that use the Adaptiv Controller safely and effectively across many different repositories.