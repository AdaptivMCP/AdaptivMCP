# Adaptiv MCP — LLM-Oriented Documentation

This document explains how an LLM/agent should use **Adaptiv MCP** tools to work with GitHub repositories via a **persistent workspace clone (repo mirror)**, plus optional quality checks and PR workflows.

> Scope: This is **operational documentation** for an LLM using the Adaptiv MCP tool surface (clone/sync/read/edit/test/commit/PR). It is not a user-facing product overview.

---

## Mental model

### 1) Persistent workspace clone (repo mirror)
Most "workspace_*" tools operate on a server-side **git working copy** that persists across calls. Think of it like a long-lived checkout at:

- `repo_dir = <owner>__<repo>/<ref>`

Changes you make (editing files, running commands) remain until you explicitly reset/sync/discard.

### 2) `ref` is the branch context
Most tools accept `ref` (default `main`). It is the branch checked out in the workspace clone.

### 3) Sync semantics
There are three related operations:

- **Status**: `workspace_sync_status` (read-only)
- **Hard reset to remote**: `workspace_sync_to_remote` (can discard local changes)
- **Bidirectional sync**: `workspace_sync_bidirectional` (commit/push local changes, and refresh)

### 4) Two editing modes
- **Structured edits (recommended)**: `set_workspace_file_contents`, `apply_workspace_operations`, `replace_workspace_text`, etc.
- **Shell edits**: `terminal_command` (e.g., run formatter, codegen, bulk refactors)

Structured edits are easier to reason about and review; shell edits are powerful for large changes.

---

## LLM workflow quickstart

### Step 0 — Ensure the workspace clone exists
Use this once per repo/ref (idempotent):

- `ensure_workspace_clone(full_name, ref)`

### Step 1 — Check sync state
Before edits, confirm you’re on the right branch and clean:

- `workspace_sync_status(full_name, ref)`

If the clone is dirty or diverged:
- Prefer **creating a feature branch** for new work.
- If you must reset: `workspace_sync_to_remote(..., discard_local_changes=true)` (destructive).

### Step 2 — Inspect repo contents
Options:
- `rg_list_workspace_files` or `list_workspace_files` for layout
- `rg_search_workspace` / `search_workspace` to locate symbols/strings
- `get_workspace_file_contents` or `read_workspace_file_excerpt` for reading

### Step 3 — Make edits
For single/multi-file edits:
- `set_workspace_file_contents` (replace whole file)
- `apply_workspace_operations` (batch operations)
- `replace_workspace_text` / `edit_workspace_text_range` (surgical edits)

### Step 4 — Validate
- `run_tests` or `terminal_command` (project-specific)
- `run_lint_suite` / `run_quality_suite` (when available)

### Step 5 — Commit & PR
Typical:
- Create a branch: `workspace_create_branch`
- Commit/push: `commit_workspace` or `commit_workspace_files`
- Open PR: `create_pull_request` or `open_pr_for_existing_branch`

One-call convenience:
- `commit_and_open_pr_from_workspace` (commit + open PR)
- `workspace_apply_ops_and_open_pr` (create branch → apply ops → quality → commit → PR)

---

## Tool groups (cheat sheet)

### A) Workspace lifecycle / syncing
- `ensure_workspace_clone` — ensure a persistent clone exists (idempotent)
- `workspace_sync_status` — show ahead/behind/clean/diverged
- `workspace_sync_to_remote` — reset mirror to match remote (optionally discard local)
- `workspace_sync_bidirectional` — commit/push local changes, then refresh from remote
- `workspace_self_heal_branch` — repair a mangled branch state (merge/rebase/conflict)

**LLM guidance:**
- Always call `workspace_sync_status` before destructive sync.
- If `ahead>0` and user wants a clean sync, use `discard_local_changes=true`.

### B) Reading & navigation
- `rg_list_workspace_files` — fast file listing
- `scan_workspace_tree` — file metadata (hash/line count) with bounds
- `rg_search_workspace` — fast search with match locations + context
- `get_workspace_file_contents` — read full file (bounded)
- `read_workspace_file_excerpt` / `read_workspace_file_sections` — safe reading by line ranges

**LLM guidance:**
- Prefer excerpt/sections for large files.
- Use ripgrep search to find relevant entry points before reading everything.

### C) Editing
- `set_workspace_file_contents` — write/replace full file content
- `apply_workspace_operations` — batch edits across many files
- `replace_workspace_text` — replace substring occurrences
- `edit_workspace_text_range` — precise (line,col) edits
- `delete_workspace_lines` / `delete_workspace_paths` — deletions
- `move_workspace_paths` — rename/move
- `make_workspace_diff` / `workspace_git_diff` — generate/inspect diffs

**LLM guidance:**
- Prefer `apply_workspace_operations` for multi-file changes: it is atomic with rollback options.
- After edits, call `workspace_git_diff(staged=false)` to review.

### D) Quality / execution
- `terminal_command` — run arbitrary shell commands in the repo mirror
- `run_tests` — run tests (default `pytest -q`)
- `run_lint_suite` — ruff lint + format check
- `run_quality_suite` — lint + tests (+ optional type/security) in one go

**LLM guidance:**
- Avoid long-running commands without a timeout.
- If a repo is not Python, use `terminal_command` with the project’s test/lint commands.

### E) Branching, commits, PRs
- `workspace_create_branch` — create feature branch (optionally push)
- `commit_workspace` — commit everything (and optionally push)
- `commit_workspace_files` — commit a curated set of files
- `create_pull_request` / `open_pr_for_existing_branch` — open PR
- `commit_and_open_pr_from_workspace` — convenience end-to-end

**LLM guidance:**
- Do not commit directly to `main` unless explicitly instructed.
- Use descriptive branch names: `docs/adaptiv-mcp-llm`, `fix/<topic>`, `feat/<topic>`.

### F) GitHub issues / workflows (optional)
- `list_repository_issues`, `fetch_issue`, `comment_on_issue`, `update_issue`
- `list_workflow_runs`, `get_workflow_run_overview`, `get_job_logs`

### G) Render operations (optional)
If the environment is connected to Render:
- `list_render_services`, `create_render_deploy`, `get_render_logs`, etc.

---

## Recommended patterns for LLM agents

### Pattern 1 — Safe repo setup
1. `ensure_workspace_clone`
2. `workspace_sync_status`
3. If diverged/dirty: decide with the user whether to **discard**, **push**, or **branch**.

### Pattern 2 — Make a targeted change
1. Search: `rg_search_workspace(query="...")`
2. Read the smallest relevant excerpts
3. Edit with `apply_workspace_operations` or `set_workspace_file_contents`
4. Diff review: `workspace_git_diff`

### Pattern 3 — Large refactor (shell-assisted)
1. `terminal_command` to run formatter/codemod
2. `get_workspace_changes_summary`
3. `workspace_git_diff`
4. `run_tests` / `run_quality_suite`

### Pattern 4 — PR creation in one call
Use when you already know the edits you want to apply:
- `workspace_apply_ops_and_open_pr`

This is ideal for deterministic documentation updates.

---

## Destructive actions and safeguards

### Potentially destructive tools
- `workspace_sync_to_remote(..., discard_local_changes=true)`
- `delete_workspace_paths` / `delete_workspace_folders`
- `workspace_self_heal_branch(..., delete_mangled_branch=true)`

**Safeguard checklist (LLM):**
- Check `workspace_sync_status` first.
- Prefer feature branches for work-in-progress.
- Provide a diff before committing when possible.

---

## Minimal JSON examples (copy/paste patterns)

> These are schema-shaped examples, not guaranteed to match your repo.

### Ensure clone
```json
{"full_name":"OWNER/REPO","ref":"main"}
```

### Search for a symbol
```json
{"full_name":"OWNER/REPO","ref":"main","query":"MyClassName","context_lines":2}
```

### Write a file
```json
{"full_name":"OWNER/REPO","ref":"main","path":"docs/README.md","content":"# Title\n..."}
```

### Batch edit
```json
{
  "full_name":"OWNER/REPO",
  "ref":"main",
  "operations":[
    {"op":"write","path":"docs/a.md","content":"..."},
    {"op":"replace_text","path":"src/app.py","old":"foo","new":"bar","replace_all":true}
  ]
}
```

### Create branch + PR
```json
{"full_name":"OWNER/REPO","base_ref":"main","feature_ref":"docs/adaptiv-mcp-llm"}
```

---

## Notes for maintainers

- Keep this file **LLM-first**: short sections, explicit tool names, predictable patterns.
- If the tool surface changes, update the cheat sheet and quickstart first.
