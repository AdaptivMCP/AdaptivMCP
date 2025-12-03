# Assistant docs and snapshots

This document explains how assistants and advanced users should think about documentation, prompts, and snapshots when using the Adaptiv Controller GitHub MCP server as a personal controller engine.

The core idea:

- The GitHub MCP server in this repository is the stable engine.
- Your ChatGPT side controller prompt is the personal layer where you express your own style and policies.
- The controller contract and docs are the shared map between humans, assistants, and the engine.

The goal is to keep assistants grounded in what the server can actually do, while still allowing each user to evolve their own personal controller over time.

---

## 1. Sources of truth

When reasoning about capabilities, always start from live information and only then lean on prompts or memory.

1. Live MCP server configuration
   - Call `get_server_config` to see which tools and settings are active, including write gating and the configured controller repository and branch.
   - Call `list_all_actions` to see the full set of tools, annotations, and read or write status.
   - Call `controller_contract` to retrieve the versioned contract that describes expectations between controllers, assistants, and this MCP server.

2. Repository docs
   - `README.md` for high level product framing and the personal controller story.
   - `docs/WORKFLOWS.md` for recommended end to end workflows.
   - `docs/ARCHITECTURE_AND_SAFETY.md` for deeper internals and guarantees.
   - `docs/SELF_HOSTED_SETUP.md` for deployment and operator guidance.
   - This file for guidance on prompts and snapshots.

3. Controller prompts and snapshots
   - System prompts and saved snapshots in ChatGPT are important, but they can drift.
   - Treat them as a layer on top of the contract and docs, not as a replacement for them.

When there is a conflict, believe the current code, contract, and docs on the main branch of this repo, not old prompts or memories from prior chats.

Meta tools when you are unsure:

- `get_server_config` for configuration and write posture.
- `list_all_actions` and `list_write_tools` for the live tool surface.
- `validate_environment` when failures look like token or configuration problems.
- `ping_extensions` to confirm that extension modules are loaded.
- `controller_contract` when in doubt about expectations or requirements.

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
- The fact that `controller_contract` is the single contract between controllers and this server.

If you do change these, treat it as a new major version and update all prompts and docs that depend on the old behavior.

---

## 3. Designing and evolving controller prompts

Controller prompts are where you express personal style and habits. They should be:

- Descriptive rather than brittle.
- Grounded in the contract and docs instead of duplicating them word for word.
- Explicit about safety, quality, and ergonomics.

Practical guidelines for prompts:

- Safety
  - Never write directly to the main branch of the controller repo.
  - Always use branch first and PR first patterns.
  - Ask the human before enabling write actions or running heavy commands.

- Quality
  - Prefer running tests and formatters on feature branches.
  - Treat test failures as first class signals and summarize them clearly.
  - Use patch based edits for large or critical files.

- Human ergonomics
  - Accept natural language goals and translate them into tool calls.
  - Ask for clarification once or twice, not constantly.
  - Summarize at important milestones, not after every tiny step.

As the engine evolves, update controller prompts only after code, tests, and docs have been updated and merged. Include a short note in the prompt about which version or commit of the engine it targets.

---

## 4. Keeping docs in sync with behavior

Docs are part of the product. Assistants should treat them as part of every change, not an afterthought.

Before making changes:

- Read the relevant sections in `docs/` and tests.
- Confirm that the planned change fits the documented safety and workflow model.

After making changes:

- Revisit docs and tests and adjust them if behavior has changed.
- When you introduce a new tool or workflow, link it from the appropriate docs.

Use the usual branch and PR flow for docs:

- Create or reuse a feature branch.
- Use text or patch based tools to update markdown files.
- Keep changes focused and reviewable.

If you are not sure how to document something, open or update a docs focused issue and propose a structure there before modifying files.

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

## 7. Large files and JSON helpers

Large files and structured payloads are common when you are driving a controller through GitHub. The engine provides helpers for both.

For large files:

- Use `get_file_slice` to read only the region you care about instead of the entire file.
- Use `build_section_based_diff` to construct diffs for the specific line ranges that need to change.
- Apply the resulting patch with `apply_patch_and_commit` on the appropriate branch.

For JSON payloads:

- Use `validate_json_string` when you are building complex JSON, such as large `sections` arrays for section based diffs.
- Use the normalized JSON returned by that tool so that whitespace differences do not cause surprises.

The goal is to keep edits small, precise, and easy to review while still supporting big files and strict JSON contracts.

---

## 8. Execution environment

When you need to run tests or commands, always think in terms of the workspace model exposed by this engine.

- `run_command` clones the target repo at a given ref into a persistent workspace and runs a command there.
- `run_tests` is a focused wrapper around `run_command` for test commands.
- Workspaces are persistent per repo/ref and shared with `commit_workspace`, so edits and installs survive between calls until explicitly reset.

Prompts and workflows should

- Avoid assuming that packages are globally installed in the controller process.
- Treat `run_command` and `run_tests` as the canonical way to execute code and tests.
- Explicitly describe what is being run and why when invoking these tools.

---

## 9. Troubleshooting when things feel stuck

When a workflow feels stuck or you see repeated failures, use this checklist instead of looping on the same tool call.

1. Stop repeating failing calls.
2. Summarize what you tried, including errors and any truncation flags.
3. Re run `controller_contract` and reopen the relevant docs.
4. Use `validate_tool_args` for complex or write tagged tools.
5. Use `validate_environment` if you suspect configuration or token problems.
6. Use `get_branch_summary` and `open_issue_context` to understand branch and issue state.
7. Propose a smaller, more observable next action.
8. Ask the human which direction to take if ambiguity remains.

This keeps assistants from silently spinning in loops and surfaces problems quickly so humans can intervene.

---

## 10. Summary

For Adaptiv Controller, the contract, docs, and engine are the stable part of the system. Your controller prompts and personal workflows are the adaptive part.

Use the meta tools and docs in this repo as your ground truth, keep prompts aligned with them, and treat issues and PRs as the way humans and assistants coordinate long running work. That way, your personal controller stays trustworthy and gets more helpful as you teach it your own way of building software.