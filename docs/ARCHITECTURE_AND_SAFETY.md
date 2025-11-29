# Adaptiv Controller Architecture and Safety

This document explains how the Adaptiv Controller GitHub MCP server is structured and which safety guarantees it provides. It is intended for operators and engineers who want to understand what the server will and will not do when used from a controller such as 'Joey's GitHub'.

For workflow examples, see `docs/WORKFLOWS.md`. For assistant mental models and snapshot guidance, see `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md`.

---

## 1. Main components

The server is organized around two Python modules:

- `main.py`
  - Defines most MCP tools (read and write).
  - Implements the `mcp_tool` decorator and global tool registry.
  - Contains commit orchestration helpers and workspace commands.
  - Exposes issue and PR helpers, search utilities, and background read tools.

- `extra_tools.py`
  - Adds additional tools via `register_extra_tools(mcp_tool)`, without changing `main.py`.
  - Currently includes file deletion and remote branch deletion helpers.

From ChatGPT's point of view the important surface is the set of tools returned by `list_all_actions`. Everything else in this document explains how those tools behave under the hood.

---

## 2. Tool registration and registry

All tools are defined using a custom `mcp_tool` decorator. It wraps FastMCP's `@mcp.tool` and standardizes metadata:

- Tags each tool as read or write.
- Sets `meta.write_action` and `meta.auto_approved`.
- Sets `ToolAnnotations.readOnlyHint` for read-only tools.
- Registers each tool in a global list `_REGISTERED_MCP_TOOLS`.

This registry powers:

- `list_all_actions`, which returns every registered tool (including those from `extra_tools.py`).
- `list_write_tools`, which summarizes write-capable tools for controller prompts and safety docs.

Because `extra_tools.register_extra_tools(mcp_tool)` uses the same decorator, extra tools participate in the same registry and safety model.

---

## 3. Write safety model

Destructive operations are gated by a global flag and explicit tagging.

### 3.1 Global write flag

- A global boolean `WRITE_ALLOWED` determines whether write tools may run.
- `authorize_write_actions(approved: bool)` is the only tool that toggles this flag.
- All tools created with `mcp_tool(write_action=True, ...)` call `_ensure_write_allowed(context)` before doing any destructive work.

`_ensure_write_allowed`:

- Inspects `WRITE_ALLOWED`.
- Raises a dedicated error if writes are not currently allowed.
- Receives a human-readable context string that usually includes the repo and branch, for example `owner/repo@branch`.

### 3.2 Read vs write tools

- Read tools (for example `get_file_contents`, `get_file_slice`, `list_repository_tree`, `search`) do not consult `WRITE_ALLOWED` and are tagged read-only.
- Write tools (for example `apply_text_update_and_commit`, `apply_patch_and_commit`, `update_files_and_open_pr`, `delete_file`, `run_command`, `run_tests`, issue helpers) are tagged with `write_action=True` and must pass through `_ensure_write_allowed`.

This design lets a controller keep the server in a read-only posture by default and only enable writes when the user explicitly approves.

Tests for the write gate live in `tests/test_write_gate.py`.

---

## 4. Controller-aware branch and ref scoping

The server is extra careful when operating on its own repository, so it does not accidentally write to `main`.

### 4.1 Effective ref helper

`_effective_ref_for_repo(full_name, ref)` centralizes default branch behavior:

- If `full_name` matches the controller repo (from `CONTROLLER_REPO`):
  - Missing or `main` refs are remapped to `CONTROLLER_DEFAULT_BRANCH` (for example the refactor branch).
  - Any other explicit ref is used as-is.

- For any other repository:
  - Missing refs default to `main`.
  - Explicit refs are used as given.

This makes it hard for assistants to accidentally write to the controller's `main` branch while refactor work is ongoing, but still keeps default behavior simple for user repos.

### 4.2 Where effective refs are used

The helper is used in multiple subsystems:

- GitHub content reads (`_decode_github_content`, `get_file_contents`, `get_file_slice`).
- Workspace cloning (`_clone_repo`), which powers `run_command` and `run_tests`.
- Extra tools in `extra_tools.py` such as `delete_file` and `delete_remote_branch`.

Tests in `tests/test_branch_scoping.py` verify that:

- Controller repos and non-controller repos behave differently with missing refs.
- Workspace and extra tools respect the effective ref, not the raw user string.

---

## 5. Commit orchestration helpers

Rather than inlining raw GitHub API calls everywhere, the server uses a small set of helpers to implement write flows. They all follow the same pattern:

1. Read the current state.
2. Compute the desired change (text or patch).
3. Commit via a single helper.
4. Re-read and verify using GitHub's Contents API and SHAs.

### 5.1 _perform_github_commit

`_perform_github_commit` is the low-level wrapper over the GitHub Contents API. It accepts:

- `full_name`: `owner/repo`.
- `path`: file path.
- `message`: commit message.
- `body_bytes`: file content as bytes.
- `branch`: target branch.
- `sha`: previous file SHA, or `None` when creating a new file.

Other helpers call this rather than constructing ad-hoc API requests.

### 5.2 apply_text_update_and_commit

`apply_text_update_and_commit` handles single-file text updates and creation:

- Uses `_effective_ref_for_repo` to choose a branch.
- Calls `_decode_github_content` to see if the file exists.
  - If it exists, records the current contents and SHA.
  - If GitHub returns a 404, treats the file as new (no prior SHA).
- Selects a commit message based on whether this is a new file or an update.
- Calls `_perform_github_commit`.
- Re-reads the file from GitHub and records `sha_after` and verified contents.
- Optionally includes a unified diff between old and new text in the result.

Tests in `tests/test_apply_text_update_and_commit.py` cover both the existing-file and new-file paths.

### 5.3 apply_patch_and_commit

`apply_patch_and_commit` applies a unified diff patch:

- Reads the original file via `_decode_github_content`.
- Applies the diff using `_apply_unified_diff_to_text`, which validates context lines and positions.
- If the patch does not match the original text, raises a `GitHubAPIError` instead of producing a broken file.
- Commits the result with `_perform_github_commit` using the original SHA.
- Re-reads and verifies the new file.

This helper is the default choice for localized code edits and is used heavily in the workflows described in `docs/WORKFLOWS.md`.

### 5.4 update_files_and_open_pr

`update_files_and_open_pr` orchestrates multi-file changes and PR creation:

- Ensures a feature branch exists from a base branch.
- Commits each file change using `_perform_github_commit`, verifying each commit by re-reading the file.
- Only opens a pull request if all commits and verifications succeed.

Tests in `tests/test_update_files_and_open_pr.py` validate this behavior.

---

## 6. Workspace execution and truncation

Two tools, `run_command` and `run_tests`, execute commands in a real cloned workspace. They are useful for running tests, linters, or migrations after a change.

### 6.1 Workspace model

Both tools:

- Compute an effective ref using `_effective_ref_for_repo`.
- Use `_ensure_write_allowed` with a context string that includes repo and branch.
- Clone the repo at the effective ref into a temporary directory using `_clone_repo`.
- Optionally create a temporary virtual environment for installing dependencies.
- Run the command using `_run_shell`.
- Return exit code, timeout status, stdout, stderr, and truncation flags.

### 6.2 Output truncation

To avoid huge outputs, `_run_shell` enforces character limits using:

- `TOOL_STDOUT_MAX_CHARS`.
- `TOOL_STDERR_MAX_CHARS`.

If a command produces more output than allowed, the server trims the strings and sets:

- `stdout_truncated = True` and/or `stderr_truncated = True`.

This makes it safe to run noisy commands while still returning enough information for the assistant to summarize or debug.

---

## 7. Issues and PR helpers

The server provides tools for working with GitHub issues and pull requests so that assistants can keep a high-level human-readable record of work.

### 7.1 Issue tools

Issue tools include:

- `create_issue`.
- `update_issue`.
- `comment_on_issue`.

They:

- Validate `full_name` and required fields.
- Enforce `_ensure_write_allowed` with context strings that mention the repo and issue number.
- Call the appropriate GitHub REST endpoints for creating, updating, and commenting.
- Propagate `GitHubAPIError` when GitHub returns an error.

`tests/test_issue_tools.py` covers validation, payload shapes, write gating, and error propagation for these tools.

### 7.2 PR tools

PR helpers include:

- `create_pull_request`, `list_pull_requests`, `merge_pull_request`, `close_pull_request`, `comment_on_pull_request`.

They follow the same general approach:

- Validate inputs.
- Enforce `_ensure_write_allowed`.
- Wrap the corresponding GitHub REST endpoints.

These tools work together with the commit orchestrations described above to support branch-first workflows where every change is reviewed in a pull request.

---

## 8. Background reads and tool discovery

For long-running read tasks, the server exposes background read helpers:

- `start_background_read`.
- `get_background_read`.
- `list_background_reads`.

Only tools that are tagged as read-only are eligible for background execution. This ensures background reads cannot bypass the write gating system.

For discovering the current tool surface, use:

- `list_all_actions` to inspect all available tools.
- `list_write_tools` to see which ones are write-capable.

Assistants should use these discovery tools rather than relying on hard-coded tool lists in prompts.

---
## 9. Tool-level structured logging

The server emits structured logs around every MCP tool call using a dedicated
logger namespace:

- Logger: `github_mcp.tools`.
- Events: `tool_call_start`, `tool_call_success`, `tool_call_error`.

The `mcp_tool` decorator wraps both read and write tools and records:

- `tool_name`: the FastMCP tool name.
- `write_action`: whether the tool is tagged as write-capable.
- `tags`: the final tag set, including `read` and `write`.
- `call_id`: a per-invocation UUID so operators can correlate start, success,
  and error events.
- `repo`, `ref`, `path`: coarse context extracted from arguments when
  available (for example `full_name`, `branch`, and `path`).
- `arg_keys`: the names of bound arguments, without logging full payloads.
- `duration_ms`: execution time for the tool call.
- `status`: values such as `ok` on success or `error` when an exception is raised.
- `error_type`: the exception type name for failures.
- `result_type` and `result_size_hint`: high-level hints about the returned
  value without serializing full results.

These logs are intended for operators and observability backends rather than
for end users. They make it possible to trace how tools are used and how long
they take without leaking secrets or large request bodies into log streams.

---

## 10. Tests and guarantees

The behaviors described in this document are backed by a set of tests, including:

- `tests/test_write_gate.py` for write gating and `WRITE_ALLOWED`.
- `tests/test_branch_scoping.py` for controller-aware ref behavior and branch scoping.
- `tests/test_update_files_and_open_pr.py` for multi-file PR orchestration.
- `tests/test_apply_text_update_and_commit.py` for text-based commit flows and new file creation.
- Workspace-related tests for `run_command` and truncation.
- `tests/test_issue_tools.py` for issue-related behavior.
- `tests/test_tool_logging.py` and `tests/test_tool_logging_write_tools.py` for tool-level logging behavior (read and write tools).
When adding new tools or changing behavior, update tests alongside the code so that these guarantees remain true over time.

## 11. How to use this document

Use this document when you need to:

- Understand how the server chooses branches and refs.
- Reason about when writes are allowed and what they can do.
- Map runtime behavior back to specific helpers and tests.

When introducing a new write tool, follow this checklist:

1. Decide whether it is read-only or write-capable.
2. Wrap it with `mcp_tool`, setting `write_action=True` when appropriate.
3. Call `_ensure_write_allowed` with a clear context string.
4. Use `_effective_ref_for_repo` for any repo + ref or repo + branch inputs.
5. Reuse commit orchestration helpers where possible instead of using raw GitHub API calls.
6. Add tests that cover the happy path and failure modes.
7. Update `ARCHITECTURE_AND_SAFETY.md`, `WORKFLOWS.md`, and any assistant docs as needed.

This keeps the Adaptiv Controller safe, predictable, and easy to reason about for both humans and AI assistants.