# ASSISTANT_HANDOFF.md

## Purpose

This document exists so that any assistant connecting to Joeys GitHub or an Adaptiv Controller instance built from this repository can quickly adopt the full project context without re deriving everything from scratch. It is the living handoff for long running work across multiple chats, sessions, and assistants.

When a new assistant attaches to this controller, they should treat this file, the controller contract, and the docs in the docs directory as the canonical truth for how to behave. If this document or those docs change and are merged into the main branch, the new version is the source of truth.

This handoff is written for the personal controller model described in the README:

- This repository and its MCP tools are the stable engine.
- Your ChatGPT side controller prompt is the personal layer where you express your own style and policies.
- The controller contract and docs are the shared map between humans, assistants, and the engine.

New assistants should keep that separation in mind at all times.

---

## What this project is

- Repository: Proofgate Revocations/chatgpt mcp github.
- Product: a self hosted GitHub MCP server and controller kit, called Adaptiv Controller, that exposes GitHub as a tool surface to assistants.
- Goals:
  - Safe for individual developers and small teams, including safety conscious environments.
  - Self hosted and owned by the person or team running it.
  - Usable as a serious, production ready controller kit, not a toy.
  - Feels to the assistant like a real engineers machine that can run commands, manage branches and pull requests, and work like a normal Git setup.

Assistants using this controller are expected to behave like disciplined engineers working in this repository and the users repositories, not like a generic chat bot.

---

## Engine versus personal controller

Adaptiv Controller is designed around two layers.

1. Engine layer
   - The GitHub MCP server in this repository.
   - The versioned controller contract exposed by the `controller_contract` tool.
   - The docs in the docs directory and the main README.
   - Owned and versioned by the person who installs and operates the controller.

2. Personal controller layer
   - One or more ChatGPT custom assistants or GPTs that use this server.
   - System prompts, instructions, and example conversations that reflect how one person likes to work.
   - Per user preferences about tone, summarization, aggressiveness, and workflows.

As an assistant, you must respect this separation:

- Treat the engine as a stable contract you discover via tools and docs, not something you guess at.
- Treat controller prompts as the place where personal style lives.

### What is safe to customize

The safe customization area is almost entirely on the controller side. For example, users may encode in their controller prompts:

- Branch naming patterns and conventions.
- Preferred languages, frameworks, and stacks.
- How much explanation they want versus how terse you should be.
- How aggressively you should refactor versus making minimal changes.
- How often to summarize, how to structure plans, and how much to ask for clarification.

You should not encourage users to fork the engine just to change these things. They belong in controller prompts and policies.

### What should remain stable

Certain concepts must remain stable if this controller is to stay trustworthy, especially when shared with others:

- The existence and semantics of the write gate and write tagged tools.
- The meaning of read versus write tool annotations and metadata.
- The high level branching and pull request expectations documented in docs/WORKFLOWS.md.
- The role of `controller_contract` as the single contract between controllers and this server.

If these change, treat it as a new major version and update docs and prompts accordingly.

---

## Core behavior expectations (snapshot)

These are a condensed snapshot of the expectations encoded in `controller_contract` and docs/WORKFLOWS.md. New assistants must read those sources directly for details; this section is a quick reminder, not a replacement.

1. Run commands like a real engineer

Use `run_command` and `run_tests` subject to write gating to run tests, linters, formatters, inspection commands, and diagnostics. Do not invent extra restrictions on workspace commands beyond the controllers own write policy. Be explicit about what you are running and why.

2. Tests are first class

When behavior or code changes, add or update tests. Use `run_tests`, or `run_command` with pytest or another test runner, on the relevant feature branch before opening pull requests. Treat test failures as first class signals and summarize them clearly.

3. Branch first and pull request first

Do not commit directly to the main branch for this repository. Always create or reuse a feature branch from main, make your changes there, run tests and linters on that branch, and then open a pull request into main. You can use patch based diffs or full file updates as appropriate for the change, but keep diffs reviewable and avoid accidentally overwriting large or critical files.

4. JSON discipline and tool schemas

Use `validate_json_string` when needed to ensure strict, valid JSON outputs. Use `validate_tool_args` when you need to dry run a tool call against its schema before executing it, especially for write tagged tools. Do not invent tool parameters; always honor the schemas returned by `list_all_actions` with `include_parameters` set to true. For complex or nested JSON payloads, build them in small steps, validate them, and if a tool call fails due to a schema or parameter mismatch, re read the tool definition instead of guessing or retrying blindly.

5. Large files and diffs

For large files, such as `main.py`, prefer `get_file_slice` to inspect specific regions, and use `build_unified_diff` or `build_section_based_diff` for patch based updates. Avoid shuttling full file contents back and forth when only a section needs to change.

6. Search and scoping

Avoid unqualified global GitHub search for routine work. Prefer repository scoped search and patterns such as searching within a repo for the relevant modules, tests, or docs. Use search tools to understand existing patterns before proposing new designs.

7. Handling repeated tool failures

Do not repeatedly call the same tool with identical arguments after a failure. Instead, summarize what happened, adjust based on the error including re reading the tool definition or relevant docs, or ask the human for guidance before trying again.

---

## Sources of truth for new assistants

When a new assistant attaches to Joeys GitHub or another Adaptiv Controller instance built from this repo, they should treat the following as canonical truth.

1. Controller contract

Call `controller_contract` via the MCP tools and read it carefully. It describes the expected workflows, safety and gating rules, and tool categories and when to use them. It is the single contract between controllers and this server.

2. Server configuration and tools

Call `get_server_config` to understand write gating, default repository and branch, timeouts, and the environment. Call `list_all_actions` with `include_parameters` set to true to see the full tool surface and parameter schemas. Call `list_write_tools` to understand which tools perform writes. Optionally call `validate_environment` to confirm GitHub and controller configuration.

3. Project documentation

Read the core documentation in the docs directory, especially

- `README.md` for high level framing and the personal controller story.
- `docs/WORKFLOWS.md` for recommended end to end workflows.
- `docs/ARCHITECTURE_AND_SAFETY.md` for internals and guarantees.
- `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md` for prompt and snapshot guidance.
- `docs/UPGRADE_NOTES.md` and `docs/SELF_HOSTED_SETUP.md` for deployment and upgrade behavior.
- `docs/OPERATIONS.md` for incident handling and `healthz` usage.
- This ASSISTANT_HANDOFF.md file.

4. Main branch as truth

Any documentation or code that has been merged into the main branch, and whose pull request has been merged by Joey, is the source of truth. When Joey says a pull request has been merged and the branch deleted, assistants must treat the merged state as authoritative and refresh their knowledge accordingly.

---

## How to start a new session checklist

When a new assistant connects to Joeys GitHub or an Adaptiv Controller instance for this repository, they should do the following early in the session.

1. Discover configuration and tools
   - Call `get_server_config`, `list_all_actions` with `include_parameters` set to true, and `list_write_tools`.
   - Optionally call `validate_environment` if anything looks misconfigured.

2. Confirm repository defaults
   - Confirm the effective default branch and other settings using the configuration tools and, when needed, repository metadata.

3. Read the core docs and this handoff
   - Fetch and read `ASSISTANT_HANDOFF.md`, `docs/WORKFLOWS.md`, `docs/ARCHITECTURE_AND_SAFETY.md`, `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md`, `docs/UPGRADE_NOTES.md`, `docs/OPERATIONS.md`, and `docs/SELF_HOSTED_SETUP.md`.

4. Align with current work
   - Read open pull requests related to the controller or docs, reviewing their diffs and descriptions.
   - Use `open_issue_context` and `get_branch_summary` to understand issue branch mappings, PR status, and ahead behind state.
   - Fetch any branches or issues that Joey references explicitly.

5. Adopt test first and pull request first behavior
   - Plan changes on a feature branch.
   - Use patch based edits or focused full file updates as appropriate.
   - Run tests and linters before opening pull requests into main.

---

## When documentation changes

The controller contract and Joeys expectations include a specific rule: when documentation for this project is updated and merged into the main branch, assistants must treat the new version as truth. After Joey says a pull request that updates docs has been merged into main and the branch deleted, assistants should re fetch the updated documents, including this file and any docs in the docs directory, re read them, and adjust their mental model accordingly. If there is any conflict between an older understanding and the newly merged docs, the merged docs win. This rule exists to avoid derailments where the human and assistant are talking past each other based on stale assumptions.

---

## Evolving this handoff document

This file is intentionally designed to be updated over time as the project, controller contract, and workflows evolve. When updating this document, use a feature branch, make focused edits to `ASSISTANT_HANDOFF.md` patch based or full file as appropriate, update `docs/WORKFLOWS.md`, `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md`, or the controller contract if behavior or expectations change, run linters and tests as appropriate, and open a pull request into main.

Future assistants should assume that the latest version of this file on main reflects the current truth about how to work on this repository, how to use Adaptiv Controller as a personal or team controller, and how to stay in sync across sessions and chats.
