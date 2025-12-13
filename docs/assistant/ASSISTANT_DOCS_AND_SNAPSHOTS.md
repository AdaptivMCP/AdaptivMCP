# Assistant docs and snapshots

This document explains how assistants and advanced users should think about documentation, prompts, and snapshots when using the Adaptiv Controller GitHub MCP server as a personal controller engine.

## How to think about this controller

At a high level:

- The GitHub MCP server in this repository is the stable engine.
- Your ChatGPT side controller prompt is the personal layer where you express your own style and policies.
In practice, always remember:

- The default branch of this repository (for example `main`) is the long-term source of truth for behavior and docs **after** humans have reviewed and merged pull requests. While you are doing work, you must not target that branch directly with MCP tools; instead, create or ensure a feature branch from the default branch and treat that feature branch as your effective main until the PR is merged and the branch is closed.
- Any local workspace clone is a scratchpad; after you use `commit_workspace` or `commit_workspace_files` to push changes from it, refresh that workspace with `ensure_workspace_clone(reset=true)` on the same branch before running tests, linters, PR helpers, or further edits. This reclone step is mandatory and not skippable.
- Tools exposed by this MCP server are the only way assistants interact with the repository. Before using any tool in a session, call `describe_tool` for that tool and, when applicable, use `validate_tool_args` on your planned `args` so you work from the live schema instead of guesses. When you need metadata or validation for multiple tools, prefer a single `describe_tool` or `validate_tool_args` call with up to 10 tools at once instead of many separate calls.
- Use branches and pull requests for any edits; avoid writing directly to the default branch, and never claim to have run a tool unless it actually executed through this server.

The goal is to keep assistants grounded in what the server can actually do, while still allowing each user to evolve their own personal controller over time. When I am running as a controller assistant (for example Joeys GitHub), I treat this repo, its tools, and these docs as the live contract that governs how I behave; my own system prompt and snapshots simply describe how I should apply that contract for a particular human.
---

## 1. Sources of truth

When reasoning about capabilities, always start from live information and only then lean on prompts or memory.

1. Live MCP server configuration
   - Call `get_server_config` to see which tools and settings are active, including write gating and the configured controller repository and branch.
   - Call `list_all_actions` to see the full set of tools, annotations, and read or write status.
   - Review the repository docs to understand the expectations between controllers, assistants, and this MCP server.

2. Repository docs
   - `README.md` for high level product framing and the personal controller story.
   - `docs/WORKFLOWS.md` for recommended end to end workflows.
   - `docs/ARCHITECTURE_AND_SAFETY.md` for deeper internals and guarantees.
   - `docs/SELF_HOSTED_SETUP.md` for deployment and operator guidance.
   - This file for guidance on prompts and snapshots.

3. Controller prompts and snapshots
   - System prompts and saved snapshots in ChatGPT are important, but they can drift.
   - Treat them as a layer on top of the contract and docs, not as a replacement for them.

When there is a conflict, believe the current code, contract, and docs on the default branch of this repo after merges, not old prompts or memories from prior chats, and never override the contract or docs just because a snapshot suggests older behavior.

Meta tools when you are unsure:

- `get_server_config` for configuration and write posture.
- `list_all_actions` and `list_write_tools` for the live tool surface.
- `describe_tool` when you need a focused view of a single tool, including its `input_schema`.
- `validate_tool_args` to preflight JSON payloads against a tool's schema (for example before calling `compare_refs` or diff/commit helpers).
- `validate_environment` when failures look like token or configuration problems.
- `ping_extensions` to confirm that extension modules are loaded.
- Repository docs when in doubt about expectations or requirements.
- `build_pr_summary` when preparing to open or update a PR so you can produce a structured `title` and `body` that reflect the latest tests, lint status, and changed areas instead of writing ad-hoc descriptions.

### 1.1 Rehydrating after context loss

Assistants sometimes lose history between turns. When that happens, rebuild context explicitly before acting:

- Start with the repository docs to refresh expectations and verify current guidance.
- Call `get_server_config` to confirm write posture, controller defaults, and uptime.
- Reopen the task surface: use `get_branch_summary` for branch state, `open_issue_context` when work is tied to an issue, and `list_repository_tree` to reorient on the repo layout.
- Pull the exact files you need again with `get_file_contents`, `get_file_slice`, or `fetch_files` instead of relying on hazy memory.
- Run quick, scoped discovery commands through `run_command` (for example `ls`, `git status`, or `rg <pattern> . --max-count 50`) to rebuild a mental map of the workspace; keep searches repo-scoped instead of global when working on this controller.
- Restate the goal and current findings in the chat so subsequent turns keep the refreshed context visible to both you and the user.

---

## 2. Engine versus personal controller

Adaptiv Controller is designed so that you can treat the MCP server as a stable engine while you evolve your own controller prompts on the ChatGPT side.

Think in two layers.

1. Engine layer
   - This repository and its MCP tools.
   - The controller contract that describes how tools behave and how safety works.
   - The docs in `docs/` and the main README.
   - Owned and versioned by the person who installs and operates the controller.

2. Personal controller layer
   - One or more ChatGPT custom assistants or GPTs that use this server.
   - System prompts, instructions, and example conversations.
   - Per user preferences about tone, summarization, aggressiveness, and workflows.

You can think of the engine as the part you ship as the product, and the personal controller prompts as the way each user turns that engine into their own assistant.

### 2.1 What is safe to customize

For a typical individual developer or small team, the safe customization area is all on the controller side. Examples:

- Branch naming patterns and conventions.
- Preferred languages, frameworks, and stacks.
- How much explanation you want versus how terse the assistant should be.
- How aggressively the assistant should refactor versus making minimal changes.
- How often to summarize, how to structure plans, and how much to ask for clarification.

These are all things that belong in your ChatGPT controller prompt and instructions, not in forks of the engine.

### 2.2 Advanced customization

Advanced users can optionally customize some engine behavior, but should do so deliberately and in a way that keeps the contract coherent. Examples:

- Adding new tools or orchestrations that wrap existing tools.
- Adjusting environment defaults, such as branch policies or workspace limits.
- Extending `extra_tools.py` with narrowly scoped helpers.

When doing this, always update tests and docs and consider whether the contract needs an explicit version bump.

### 2.3 Things that should remain stable

Some parts of the system should not be changed casually, especially if you plan to distribute this controller to others. For example:

- The existence and semantics of core safety concepts such as the write gate.
- The meaning of read versus write tool annotations.
- The high level branching and PR expectations documented in the workflows doc.
- The fact that the repository docs capture the single contract between controllers and this server.

If you do change these, treat it as a new major version and update all prompts and docs that depend on the old behavior.

---

## 3. Designing and evolving controller prompts

Controller prompts are where you express personal style and habits. They should be:

- Descriptive rather than brittle.
- Grounded in the contract and docs instead of duplicating them word for word.
- Explicit about safety, quality, and ergonomics.

Practical guidelines for prompts:

- Safety
  - Never write directly to the default branch of the controller repo.
  - Use branches and pull requests for changes instead of writing directly to protected branches, and always run tests and linters on the feature branch from a fresh workspace clone (recloned with `ensure_workspace_clone(reset=true)` after any workspace commit) before opening or updating PRs.
  - Ask the human before enabling write actions or running heavy commands.

- Quality
  - Prefer running tests and formatters on feature branches, and treat test failures as first class signals.
  - Use patch based edits for large or critical files, and keep diffs reviewable.
  - Build JSON payloads yourself and run `validate_tool_args` or `validate_json_string` before write-tagged or complex calls.

- Human ergonomics
  - Accept natural language goals and translate them into tool calls; do not ask the user to provide raw JSON payloads or schemas.
  - Ask for clarification once or twice, not constantly.
  - Summarize at important milestones, and be explicit about which tools you actually ran and what they returned.

- Human ergonomics
  - Accept natural language goals and translate them into tool calls.
  - Ask for clarification once or twice, not constantly.
  - Summarize at important milestones, not after every tiny step.

As the engine evolves, update controller prompts only after code, tests, and docs have been updated and merged. Include a short note in the prompt about which version or commit of the engine it targets.

---

## 4. Keeping docs in sync with behavior

Docs are part of the product. I treat them as part of every change, not an afterthought. When my behavior or the tools change, I assume the docs need to change too.

Before making changes:

- I read the relevant sections in `docs/` and tests.
- I confirm that the planned change fits the documented safety and workflow model described in the repository docs.

After making changes:

- I revisit docs and tests and adjust them if behavior has changed.
- When I introduce or rely on a new tool or workflow, I link it from the appropriate docs so future assistants (and future versions of me) can discover it.
- If tests or linters fail because of my changes, I take responsibility for fixing them—updating code, tests, and docs until they pass instead of leaving broken work for the human.

I use the usual branch and PR flow for docs:

- I create or reuse a feature branch.
- I use text or patch based tools to update markdown files.
- I keep changes focused and reviewable.
- I refresh my workspace after each commit before running tests or lint: once I have used `commit_workspace` or `commit_workspace_files` to push changes, I call `ensure_workspace_clone` again with `reset=true` on the same branch before any forward-moving action such as `run_tests`, `run_lint_suite`, or further edits.
- When I am ready to open a PR, I use `build_pr_summary` with the repo `full_name`, my feature branch `ref`, and a short human-written title/body plus summaries of changed files and quality results. I then render the resulting structured `title` and `body` into the PR description via the appropriate PR tool so descriptions stay consistent across assistants.

If I am not sure how to document something, I open or update a docs focused issue and propose a structure there before modifying files.
If I am not sure how to document something, I open or update a docs focused issue and propose a structure there before modifying files.

---

---

## 5. Issues as the coordination backbone

Issues are how humans and assistants coordinate work over time. For this repo and for controller repos more broadly, assistants should:

- Use issue tools to capture new work and questions.
- Keep issue bodies and checklists aligned with the current plan.
- Comment with progress, design decisions, and links to branches and PRs.

A simple pattern:

1. Open an issue at the start of substantial work.
2. Reference that issue from branches and PRs.
3. Update the issue body and checklist as the plan evolves.
4. Close the issue when all acceptance criteria are met and merged.

This pattern works just as well for solo developers as it does for teams, and it gives your personal controller a clear way to understand and search past work.

---

## 6. Snapshots, versions, and drift

Over time, prompts and snapshots can drift away from the code that actually runs. To keep things aligned:

- Include a brief version or commit reference in the controller prompt or snapshot description.
- Periodically re sync the prompt with the live tool list and docs by calling `list_all_actions` and revisiting the docs on the main branch.
- When you find a mismatch, decide whether the code, docs, or prompt should change, and then update all affected layers.

When drift is serious enough that behavior feels surprising, treat it as a bug and fix it through the usual issue and PR workflow.

---

## 7. Large files, JSON helpers, and tool selection for edits

Large files and structured payloads are common when you are driving a controller through GitHub. The engine provides helpers for both, and the choice of helper matters for safety and ergonomics.

For large files:

- Use `get_file_slice` to read only the region you care about instead of the entire file.
- Use `get_file_with_line_numbers` when you need exact line references for citations or for line-based patch tools; copy the ranges directly instead of hand-numbering snippets.
- Use `build_section_based_diff` to construct diffs for the specific line ranges that need to change.
- Apply the resulting patch with `apply_patch_and_commit` on the appropriate branch.
- Use `apply_line_edits_and_commit` for small, line-targeted updates when you know the exact line numbers.
- Use `download_user_content` when you need to pull bytes for an example or test fixture without writing a file back to the repo. It accepts:
  - `sandbox:/` paths and absolute server paths.
  - Absolute `http(s)` URLs.
  - `github:` URLs of the form `github:owner/repo:path/to/file[@ref]`, which reuse the server's GitHub token and work with private repositories.
- When I need the full contents of a large GitHub file (for example `main.py` in this controller repo), I call `download_user_content` once with a `github:` URL and then reason over that local copy instead of repeatedly slicing the same path. This keeps heavy bytes in the hidden workspace, still treats the branch head as the source of truth for patches, and avoids a flood of small file API calls.
- Reserve `apply_text_update_and_commit` for cases where you intentionally regenerate the entire file from a fresh spec or prompt.
For JSON payloads:

- Treat `validate_json_string` as a default step, not an optional rescue tool. Run it automatically when you construct non-trivial JSON (large `sections` arrays, tool arguments, or raw JSON responses) so the host always receives strict, copy-ready payloads without additional prompting.
- Use the normalized JSON returned by that tool so that whitespace differences do not cause surprises.

The goal is to keep edits small, precise, and easy to review while still supporting big files and strict JSON contracts.

---

## 8. Tool argument hygiene and escaping

Most tool call failures come from malformed JSON, stray escape sequences, or strings wrapped in extra quotes. Use this checklist to keep arguments valid and readable.

- Start from structured JSON, not a quoted blob.
  - ✅ `{"path": "src/app.py", "replacement": "Line 1\nLine 2"}`
  - ❌ `"{\"path\": \"src/app.py\", \"replacement\": \"Line 1\\nLine 2\"}"`
- Build arguments in this order to avoid over-escaping:
  1. Write the JSON object with real newlines and double quotes only where JSON requires them.
  2. Add escapes for double quotes *inside* string values, not around the whole payload.
  3. Avoid `\n` escapes inside values unless the tool explicitly expects them; prefer literal newlines or arrays.
  4. Run `validate_tool_args` (or `validate_json_string` for big blobs) before write-tagged tools to catch stray quotes. Default to pre-validating JSON so assistants are never waiting for host-side parse errors to reveal malformed payloads.
- Prefer real newlines or arrays of lines instead of `\n`-filled strings when the tool accepts them.
  - For patch tools, use multiline strings or `sections` arrays rather than sprinkling `\n` escapes.
- Escape double quotes only inside JSON string values.
  - ✅ `{ "text": "He said \"hello\" before leaving." }`
  - ❌ `{ "text": "He said "hello" before leaving." }`
- Avoid escaped newlines in argument *values* unless the tool expects them. A literal `\n` often indicates the string was over-escaped.
- Run `validate_tool_args` before write-tagged calls when in doubt; it will confirm JSON structure and surface quoting problems early.
- If a server or test harness shows `invalid arguments` errors, inspect the raw JSON payload. Remove any surrounding quotes and unescape until the JSON parses cleanly.

Teach assistants these patterns directly in prompts and examples so they stop generating over-escaped payloads.

---

## 9. Execution environment

When you need to run tests or commands, always think in terms of the workspace model exposed by this engine.

- `run_command` clones the target repo at a given ref into a persistent workspace and runs a command there.
- `run_tests` is a focused wrapper around `run_command` for test commands.
- Workspaces are persistent per repo/ref and shared with `commit_workspace`, so edits and installs survive between calls until explicitly reset.

Prompts and workflows should

- Avoid assuming that packages are globally installed in the controller process.
- Treat `run_command` and `run_tests` as the canonical way to execute code and tests.
- Explicitly describe what is being run and why when invoking these tools.

---

## 10. Troubleshooting when things feel stuck

When a workflow feels stuck or you see repeated failures, use this checklist instead of looping on the same tool call.

1. Stop repeating failing calls.
2. Summarize what you tried, including errors and any truncation flags.
3. Reopen the relevant docs to refresh expectations.
4. Use `validate_tool_args` for complex or write tagged tools.
5. Use `validate_environment` if you suspect configuration or token problems.
6. Use `get_branch_summary`, `open_issue_context`, and `get_issue_overview` to understand branch and issue state before taking further action.
7. Propose a smaller, more observable next action.
8. Ask the human which direction to take if ambiguity remains.

This keeps assistants from silently spinning in loops and surfaces problems quickly so humans can intervene.

---

## 11. Summary

For Adaptiv Controller, the contract, docs, and engine are the stable part of the system. Your controller prompts and personal workflows are the adaptive part.

Use the meta tools and docs in this repo as your ground truth, keep prompts aligned with them, and treat issues and PRs as the way humans and assistants coordinate long running work. That way, your personal controller stays trustworthy and gets more helpful as you teach it your own way of building software.