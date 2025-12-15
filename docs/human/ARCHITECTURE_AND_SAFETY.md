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

From an assistant or controller point of view the important surface is the set of tools returned by `list_all_actions`. Everything else in this document explains how those tools behave under the hood.

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

In addition to the raw tool list, the server exposes a best-effort JSON schema for each tool's arguments when possible. When an MCP tool exports an explicit input schema, that schema is returned as-is. When no schema is available, the server synthesizes a minimal `{type: 'object', properties: {}}` schema so controllers can still treat the presence of `input_schema` as a stable contract instead of a sometimes-`null` field.

Controllers and assistants can call `describe_tool` and, where it provides additional value, `validate_tool_args` against these schemas before invoking unfamiliar or write-tagged tools. For certain helpers (for example `list_workflow_runs`), the server provides a hand-authored JSON schema so validation can enforce required fields even when the upstream MCP layer has no schema configured.
---

## 3. Write safety model

Destructive operations are gated by a global flag and explicit tagging.

### 3.1 Global write flag

- The environment variable `GITHUB_MCP_AUTO_APPROVE` seeds the initial value:
  - When unset or set to a falsey value, `WRITE_ALLOWED` defaults to `False` and the
    server starts in manual approval mode.
  - When set to a truthy value (for example `1`, `true`, `yes`, or `on`),
    `WRITE_ALLOWED` defaults to `True` and the server starts in auto-approve
    mode.
- `authorize_write_actions(approved: bool)` is the only tool that toggles this
  flag at runtime. Controllers call this tool when they need to enable or
  disable write actions for a session.
- All tools created with `mcp_tool(write_action=True, ...)` call `_ensure_write_allowed(context, target_ref=...)` before doing any destructive work.

`_ensure_write_allowed`:

- Inspects `WRITE_ALLOWED`.
- Receives a human-readable context string that usually includes the repo and branch, for example `owner/repo@branch`.
- Accepts an optional `target_ref` argument so it can distinguish between writes to the controller default branch and writes to feature branches.
- For unscoped operations (no `target_ref`), enforces `WRITE_ALLOWED` as a global kill switch for dangerous tools.
- For writes that target the controller default branch (`CONTROLLER_DEFAULT_BRANCH`, typically `main`), enforces `WRITE_ALLOWED` so direct writes to the default branch always require explicit approval.
- For writes that target non-default branches, allows the operation even when `WRITE_ALLOWED` is `False`, so assistants can iterate on feature branches while leaving the default branch protected.

### 3.2 Read vs write tools

- Read tools (for example `get_file_contents`, `get_file_slice`, `list_repository_tree`, `search`) do not consult `WRITE_ALLOWED` and are tagged read-only.

This design lets a controller keep the server in a read-only posture by default and only enable writes when the user explicitly approves, while still allowing assistants to commit freely to feature branches and keeping the controller default branch protected.

### 3.3 Server configuration snapshot

The `get_server_config` tool returns a non-sensitive snapshot of the current
write policy, including:

- `write_allowed`: the current value of `WRITE_ALLOWED`.
- `approval_policy.write_actions.auto_approved`: whether the server considers
  write tools auto-approved by default.
- `approval_policy.write_actions.requires_authorization`: whether a controller
  should call `authorize_write_actions` before using write tools.
- `approval_policy.write_actions.toggle_tool`: the name of the tool that
  toggles the write flag.

Controllers can call `get_server_config` at the start of a session to decide whether they need to request user approval for writes, and can use `get_latest_branch_status` to understand the current branch head's PR and workflow state before attempting CI fixes.

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
- Workspace cloning (`_clone_repo`), which powers `terminal_command` and `run_tests`.
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

`apply_text_update_and_commit` performs full-file text updates and creation in a
single commit. Because this is powerful and easy to misuse on code-heavy files,
`update_files_and_open_pr`).
against caller-provided `new_content`; it rejects negative context sizes and
builds a patch directly from caller-supplied `original` and `updated` buffers
and also rejects negative context sizes.


- Reads the current file content from GitHub.
- Accepts a list of line-based sections (`start_line`, `end_line`, `new_text`).
- Validates that sections are sorted, non-overlapping, and in range; otherwise it raises a `ValueError` to make the refusal explicit.
- Applies those section replacements in memory.
- Calls the string-based diff helper internally to produce a unified diff patch.



Note: patches received by workspace-oriented tooling are normalized before application (unescape single-line diffs with literal \\n sequences and strip common trailing artifacts like code fences) to reduce accidental `git apply` failures.

- Reads the original file via `_decode_github_content`.
- Applies the diff using `_apply_unified_diff_to_text`, which validates context lines and positions.
- If the patch does not match the original text, raises a `GitHubAPIError` instead of producing a broken file.
- Commits the result with `_perform_github_commit` using the original SHA.
- Re-reads and verifies the new file.

This helper is the default choice for localized code edits and is used heavily in the workflows described in `docs/WORKFLOWS.md`.

### 5.3 Workspace refresh after Contents-API commits

To keep the long-lived workspace clone in sync with branches that are updated via the GitHub Contents API, the server uses a small wrapper around `_perform_github_commit`:

- `_perform_github_commit_and_refresh_workspace` calls `_perform_github_commit` and then, on success, calls `ensure_workspace_clone(full_name=..., ref=branch, reset=True)`.
- Any failure in the workspace refresh path is logged at debug level and does not affect the result of the underlying commit.


Tests in `tests/test_workspace_sync_after_commit.py` exercise this behavior by asserting that both the commit helper and `ensure_workspace_clone` are invoked with the expected parameters.

### 5.4 update_files_and_open_pr

`update_files_and_open_pr` orchestrates multi-file changes and PR creation:

- Ensures a feature branch exists from a base branch.
- Commits each file change using `_perform_github_commit`, verifying each commit by re-reading the file.
- Only opens a pull request if all commits and verifications succeed.

Tests in `tests/test_update_files_and_open_pr.py` validate this behavior.

### 5.5 Workspace and text-based commit helpers and branch-aware gating


- Commits to non-default branches are allowed even when `WRITE_ALLOWED` is `False`, so I can iterate on feature branches without elevating global write permissions.
- Direct writes to the controller default branch still require explicit approval, because `_ensure_write_allowed` treats the controller default branch as protected and enforces the global write flag there.


By contrast, unscoped or potentially dangerous write tools call `_ensure_write_allowed` with `target_ref=None`, which treats `WRITE_ALLOWED` as a global kill switch. I should assume those tools are disabled unless the controller has explicitly authorized writes via `authorize_write_actions`.

---

## 6. Workspace execution and truncation

Two tools, `terminal_command` and `run_tests`, execute commands in a real cloned workspace. They are useful for running tests, linters, or migrations after a change.

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

These tools work together with the commit orchestrations described above to support branch-based workflows where every change is reviewed in a pull request.

---

## 8. Tool discovery

For discovering the current tool surface, use:

- `list_all_actions` to inspect all available tools.
- `list_write_tools` to see which ones are write-capable.

Assistants should use these discovery tools rather than relying on hard-coded tool lists in prompts.

---

## 9. Tool-level structured logging

The server emits structured logs around every MCP tool call using a dedicated
logger namespace:

- Logger: `github_mcp.tools`.

### Environment validation tool

To make operations and debugging easier on new deployments, the controller
exposes a small read-only tool, `validate_environment`. This tool does not
perform any writes; instead it:

- Inspects process environment variables related to GitHub authentication,
  controller repository/branch selection, Git identity, and HTTP/concurrency
  tuning.
- Optionally performs lightweight GitHub API calls to confirm that the
  configured controller repository and branch exist and are accessible with the
  current token.
- Returns a structured report containing individual checks (with `ok`,
  `warning`, or `error` levels) and a summary count so assistants and operators
  can quickly identify misconfigurations such as missing tokens or mismatched
  branches.

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
- Workspace-related tests for `terminal_command` and truncation.
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
---

## In-process metrics and health endpoint

In addition to structured logs, the server maintains a small in-process metrics
registry and exposes a lightweight HTTP health endpoint.

- Metrics registry (`_METRICS`):
  - `tools`: per-tool counters maintained by `_record_tool_call`, including:
    - `calls_total`: number of times the tool was invoked.
    - `errors_total`: number of invocations that raised an exception.
    - `write_calls_total`: number of invocations for tools tagged as write actions.
    - `latency_ms_sum`: accumulated execution time across all calls.
  - `github`: aggregate counters maintained by `_record_github_request`, including:
    - `requests_total`: total GitHub client requests.
    - `errors_total`: requests that resulted in errors.
    - `rate_limit_events_total`: times where the reported remaining rate limit reached zero.
    - `timeouts_total`: requests that raised `httpx.TimeoutException`.

The helper `_metrics_snapshot()` returns a JSON-safe view of this registry and
is used by the `/healthz` HTTP route:

- `status`: string health flag.
- `uptime_seconds`: process uptime based on `SERVER_START_TIME`.
- `github_token_present`: boolean indicating whether a GitHub token is configured.
- `controller.repo` / `controller.default_branch`: the controller repository and default branch in effect.
- `metrics`: the snapshot from `_metrics_snapshot()`.

Metrics are intentionally kept in memory only; they reset on process restart
and never include request bodies, secrets, or other user content. The `/healthz`
endpoint is safe to use for uptime checks, basic dashboards, and smoke tests.

## 12. Execution environment: terminal_command and run_tests

For all code execution and tests against this repository (or any other repo accessed through this controller), assistants must treat the workspace tools as the canonical execution environment, not the MCP server process itself.

Specifically:

- `terminal_command` and `run_tests` clone the target repository at the effective ref (as computed by `_effective_ref_for_repo`) into a persistent workspace so installs and edits are preserved across calls.
- They optionally create a temporary virtual environment and run the requested command or test suite inside that workspace.
- The same workspace is reused across calls and shared with commit helpers so edits and installs persist until explicitly reset.

This means:

- Assistants should not assume any global packages or state in the MCP server process; all project-level dependencies must be managed via `terminal_command` / `run_tests` inside the cloned workspace.
- When describing workflows in docs or prompts, assume that code execution and tests always happen through these tools, on a reusable checkout of the branch being worked on.
- When new workflow tools are added that depend on executing code, they should internally use the same workspace model rather than relying on ambient process state.
