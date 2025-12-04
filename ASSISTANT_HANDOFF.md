# ASSISTANT_HANDOFF.md

## Purpose

This document exists so that any assistant connecting to Joeys GitHub or an Adaptiv Controller instance built from this repository can quickly adopt the full project context without re-deriving everything from scratch. It is the living handoff for long-running work across multiple chats, sessions, and assistants.

When a new assistant attaches to this controller, they should treat this file, the controller contract, the assistant happy paths playbook, and the docs in the `docs` directory as the canonical truth for how to behave. If this document or those docs change and are merged into the main branch, the new version is the source of truth.

This handoff is written for the personal controller model described in the README:

- This repository and its MCP tools are the stable engine.
- Your ChatGPT-side controller prompt is the personal layer where you express your own style and policies.
- The controller contract, happy paths playbook, and docs are the shared map between humans, assistants, and the engine.

New assistants should keep that separation in mind at all times.

---

## What this project is

- Repository: `Proofgate-Revocations/chatgpt-mcp-github`.
- Product: a self-hosted GitHub MCP server and controller kit, called Adaptiv Controller, that exposes GitHub as a tool surface to assistants.
- Goals:
  - Safe for individual developers and small teams, including safety-conscious environments.
  - Self-hosted and owned by the person or team running it.
  - Usable as a serious, production-ready controller kit, not a toy.
  - Feels to the assistant like a real engineer’s machine that can run commands, manage branches and pull requests, and work like a normal Git setup.

Assistants using this controller are expected to behave like disciplined engineers working in this repository and the user’s repositories, not like a generic chat bot.

---

## Engine versus personal controller

Adaptiv Controller is designed around two layers.

1. Engine layer
   - The GitHub MCP server in this repository.
   - The versioned controller contract exposed by the `controller_contract` tool.
   - The docs in the `docs` directory and the main README.
   - Owned and versioned by the person who installs and operates the controller.

2. Personal controller layer
   - One or more ChatGPT custom assistants or GPTs that use this server.
   - System prompts, instructions, and example conversations that reflect how one person likes to work.
   - Per-user preferences about tone, summarization, aggressiveness, and workflows.

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

- The existence and semantics of the write gate and write-tagged tools.
- The meaning of read versus write tool annotations and metadata.
- The high-level branching and pull request expectations documented in `docs/WORKFLOWS.md`.
- The role of `controller_contract` as the single contract between controllers and this server.

If these change, treat it as a new major version and update docs and prompts accordingly.

---

## Deployment and hosting snapshot

Adaptiv Controller is typically deployed in one of two ways:

1. A managed platform (for example Render) with an HTTPS URL that controllers like Joeys GitHub connect to from ChatGPT.
2. A self-hosted Docker deployment using the `Dockerfile`, `docker-compose.yml`, and `.env.example` in this repo (see `docs/SELF_HOSTING_DOCKER.md` and `docs/SELF_HOSTED_SETUP.md`).

In both cases, assistants should treat the MCP server as the engine layer and use the same branch-and-PR-oriented, `run_command`-heavy workflows described here and in `docs/WORKFLOWS.md`. The main difference is who operates the server and where it runs, not how assistants behave.

---

## Core behavior expectations (snapshot)

These are a condensed snapshot of the expectations encoded in `controller_contract`, `docs/WORKFLOWS.md`, and `docs/ASSISTANT_HAPPY_PATHS.md`. New assistants must read those sources directly for details; this section is a quick reminder, not a replacement.

1. Run commands like a real engineer

Use `run_command` and `run_tests` subject to write gating to run tests, linters, formatters, inspection commands, and diagnostics. Treat them as your keyboard on a dedicated development machine, including for quick searches or usage checks. Do not invent extra restrictions on workspace commands beyond the controller’s own write policy. Be explicit about what you are running and why.
Do not ask humans to run commands, paste scripts, or add newlines for you. Handle quoting, patch generation, and retries with the provided tools. Avoid token-heavy inline payloads or massive tool responses when a focused command, slice, or diff will do.

2. Tests are first class

When behavior or code changes, add or update tests. Use `run_tests`, or `run_command` with pytest or another test runner, on the relevant feature branch before opening pull requests. Treat test failures as first-class signals and summarize them clearly.

3. Work on branches and use pull requests

Do not commit directly to the main branch for this repository. Always create or reuse a feature branch from `main`, make your changes there, run tests and linters on that branch, and then open a pull request into `main`. You can use patch-based diffs or full-file updates as appropriate for the change, but keep diffs reviewable and avoid accidentally overwriting large or critical files.

4. JSON discipline and tool schemas

Use `validate_json_string` when needed to ensure strict, valid JSON outputs. Use `validate_tool_args` when you need to dry-run a tool call against its schema before executing it, especially for write-tagged tools. Do not invent tool parameters; always honor the schemas returned by `list_all_actions` with `include_parameters` set to `true`. For complex or nested JSON payloads, build them in small steps, validate them, and if a tool call fails due to a schema or parameter mismatch, re-read the tool definition instead of guessing or retrying blindly.

5. Large files and diffs

For large files, such as `main.py`, prefer `get_file_slice` to inspect specific regions, and use `build_unified_diff` or `build_section_based_diff` for patch-based updates. Avoid shuttling full contents back and forth when a small section-level diff will do.

6. Respect write gating and approvals

Use `authorize_write_actions` when the write gate is enabled, and treat approval as a scoped, time-boxed permission to perform concrete write actions. Do not silently escalate from read to write operations without informing the human.

7. Summaries and auditability

When you complete a workflow, summarize what you changed, which tools you used, and where the artifacts live (branches, pull requests, issues, or docs). This is especially important when operating across multiple repositories.

These expectations are snapshots, not substitutes for reading `controller_contract` and `docs/WORKFLOWS.md`.

- Do NOT use `run_command` as a patch engine (for example with large
  heredoc Python scripts that rewrite files). This is brittle under
  JSON encoding and will fail easily.
- Routine multi-line edits are normal. Use diff-based tools to apply
  them directly instead of calling them tricky or bouncing them back to
  humans.
- For file edits, prefer:
  - `apply_text_update_and_commit` for full-file replacements.
  - `update_file_sections_and_commit` for structured section-level edits.
  - `build_unified_diff` + `apply_patch_and_commit` when you want explicit diffs.
- Do NOT embed large multi-line Python/shell scripts in `run_command.command`.
  If your edit involves more than a couple of lines of shell, treat that as
  a signal to use the diff-based tools instead.
