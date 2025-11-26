# Human + AI Workflow Manual for the GitHub MCP Server

This manual is the single source of truth for how humans and assistants collaborate with the GitHub MCP server. It is written in natural language first, with tool names and command details kept close at hand so both audiences can read, learn, and act without guessing.

## Roles and how to talk to each other

- **Humans speak plainly.** Requests like “update that file for me” or “make a new module and create a PR” are expected. No need to describe tool calls—just describe intent, constraints, and any preferences.
- **Assistants translate intent to tools.** Choose the smallest set of MCP tools that accomplish the human request, confirm scope, and summarize what will happen before making changes.
- **Shared vocabulary.** Use the phrasing below when confirming actions:
  - *Discover*: browse or fetch repository content.
  - *Edit*: apply a patch, rewrite a file, or add/remove files.
  - *Verify*: run commands, tests, or linters in a temporary clone.
  - *Publish*: create branches, commits, and pull requests.

## Core tool map

These are the primary tools assistants will reach for. Pick the narrowest tool that fits the task to keep responses fast and safe.

- **Repository discovery**: `list_repository_tree`, `get_file_contents`, `fetch_files`.
- **Search and metadata**: `search_code`, `list_branches`, `list_workflow_runs`, `get_workflow_run`.
- **Editing and PRs**: `update_files_and_open_pr`, `apply_patch_and_open_pr`, `create_branch`, `commit_files`, `open_pull_request`.
- **Command execution**: `run_command`, `run_tests` (supply a `patch` argument when the command must run against pending edits).
- **Workflow automation**: `trigger_workflow_dispatch`, `trigger_and_wait_for_workflow`.
- **Access control**: `authorize_write_actions` (required unless auto-approve is enabled server-side).
- **Server limits and diagnostics**: `get_server_config`, `health_check`, and truncation notices in tool outputs.

## Standard workflows

Follow these recipes to translate everyday human requests into concrete steps. Combine or reorder them as needed—each recipe is deliberately small and interoperable.

### 1) Recon and understanding
- Confirm write access: `get_server_config`; if writes are locked, run `authorize_write_actions approved=true` after human approval.
- Map the repo: `list_repository_tree` (use `path_prefix` to focus) and `search_code` for quick grep-like queries.
- Read files with line numbers: `get_file_contents` for single files or `fetch_files` for batches.

### 2) Plan an edit or new module
- Restate the human ask in plain language and list the files you expect to touch.
- Pull fresh content with `get_file_contents`/`fetch_files` so line numbers match.
- Outline the change and ask for confirmation when scope is ambiguous.

### 3) Apply changes and open a PR
- Preferred one-shot path: `update_files_and_open_pr` with `{path, content}` items plus PR title/body.
- Alternative when patching is simpler: `apply_patch_and_open_pr` with a unified diff.
- If you need intermediate commits:
  1. `create_branch`
  2. `commit_files` (can be repeated)
  3. `open_pull_request`
- Always report any truncation noted in tool responses and include test output in the final summary.

### 4) Run commands, tests, or linters
- For changes not yet committed, pass a `patch` to `run_command` or `run_tests` so the temporary clone mirrors your edits.
- Keep commands focused (single test suite or linter at a time) to minimize truncation and surface failures clearly.
- Include the exact command and whether it passed or failed in your final report.

### 5) Handle CI workflows
- To rerun or dispatch CI: `trigger_workflow_dispatch` with the workflow filename and inputs.
- To block until completion: `trigger_and_wait_for_workflow` and relay the final status plus any notable logs.
- To debug recent runs: `list_workflow_runs` then `get_workflow_run` for details.

### 6) Responding to natural language
- "Update that file for me": fetch current content, propose the change, then use `update_files_and_open_pr` (or `apply_patch_and_open_pr`) to commit and open a PR.
- "Make that new module": create the file content locally, add it via `update_files_and_open_pr`, and note any imports or wiring changes.
- "Run the tests": choose the relevant command, run via `run_tests`/`run_command` (with `patch` if needed), and summarize results.
- "Create a PR": if changes already exist in a branch, call `open_pull_request`; otherwise prefer the bundled edit-and-PR tools above.

## Reporting expectations

- Summaries must be readable by humans without tool knowledge. Lead with what changed, then cite files and commands.
- Always disclose:
  - Which tools were used and why.
  - Any truncation or skipped steps.
  - Test/command outcomes with the exact command text.
- If blocked (permissions, missing files, failing tests), explain the failure plainly and propose next steps.

## When in doubt

- Prefer small, reversible steps and ask for confirmation on high-impact actions.
- If a human request is unclear, mirror back what you plan to do and which tools you will use.
- Keep the conversation in natural language; tool names are implementation details to share for transparency, not for the human to memorize.
