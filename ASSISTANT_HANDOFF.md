# ASSISTANT_HANDOFF.md

## Purpose

This document exists so that any assistant connecting to Joey's GitHub / Adaptiv Controller can quickly adopt the full project context without re-deriving everything from scratch. It is the living handoff for long-running work across multiple chats, sessions, and assistants.

When a new assistant attaches to this controller, they should treat this file, the controller contract in main.py, and the docs in the docs/ directory as the canonical truth for how to behave. If this document or those docs change and are merged into the main branch, the new version is the source of truth.

## What this project is

- Repository: Proofgate-Revocations/chatgpt-mcp-github.
- Product: a self-hosted MCP controller (Adaptiv Controller) that exposes GitHub as a tool surface to assistants.
- Goals:
  - Safe for safety-critical teams.
  - Self-hosted and owned by the customer.
  - Usable as a serious, commercial-ready product (controller plus consulting bundle), not a toy.
  - Feels to the assistant like a real engineer's machine that can run commands, manage branches and pull requests, and work like a normal Git setup.

Assistants using this controller are expected to behave like disciplined engineers working in this repository, not like a generic chat bot.

## Core behavior expectations (snapshot)

These are a condensed snapshot of the expectations encoded in controller_contract and docs/WORKFLOWS.md. New assistants must read those sources directly for details; this section is a quick reminder, not a replacement.

1. Run commands like a real engineer

Use run_command freely, subject to write gating, to run tests, run linters and formatters, inspect files, run git commands, and perform diagnostics. Do not invent extra restrictions on run_command beyond the controller's own write policy.

2. Tests are first-class

When behavior or code changes, add or update tests. Use run_tests, or run_command with pytest, on the relevant feature branch before opening pull requests.

3. Branch-first, patch-first, pull-request-first

Do not commit directly to the main branch for this repository. Always create or reuse a feature branch from main, make changes there using patch-based flows such as build_unified_diff, build_section_based_diff, and apply_patch_and_commit, run tests and linters on that branch, and then open a pull request into main. Joey reviews, merges, and deletes branches.

4. JSON discipline

Use validate_json_string when needed to ensure strict, valid JSON outputs. Do not invent tool parameters; always honor the schemas returned by list_all_actions with the include_parameters flag set to true.

5. Large files and diffs

For large files, such as main.py, prefer get_file_slice to inspect specific regions, and use build_unified_diff, build_unified_diff_from_strings, or build_section_based_diff for patch-based updates.

6. Search and scoping

Avoid unqualified global GitHub search for routine work. Prefer repository-scoped search and helpers such as search_code_in_repo.

## Sources of truth for new assistants

When a new assistant attaches to Joey's GitHub or Adaptiv Controller, they should treat the following as canonical truth.

1. Controller contract

Call controller_contract via the MCP tools and read it carefully. It describes the expected workflows, safety and gating rules, and tool categories and when to use them.

2. Server configuration and tools

Call get_server_config to understand write gating, default repository and branch, timeouts, and the environment. Call list_all_actions with include_parameters set to true to see the full tool surface and parameter schemas. Call list_write_tools to understand which tools perform writes. Optionally call validate_environment to confirm GitHub and controller configuration.

3. Project documentation

Read the core documentation in the docs directory, especially WORKFLOWS.md, ARCHITECTURE_AND_SAFETY.md, and ASSISTANT_DOCS_AND_SNAPSHOTS.md. Read this ASSISTANT_HANDOFF.md file in full as part of session bootstrap.

4. Main branch as truth

Any documentation or code that has been merged into the main branch, and whose pull request has been merged by Joey, is the source of truth. When Joey says a pull request has been merged and the branch deleted, assistants must treat the merged state as authoritative and refresh their knowledge accordingly.

## How to start a new session checklist

When a new assistant connects to Joey's GitHub or Adaptiv Controller for this repository, they should do the following early in the session.

1. Discover configuration and tools by calling get_server_config, list_all_actions with include_parameters set to true, and list_write_tools.

2. Confirm repository defaults by calling get_repo_defaults or inspecting repository metadata to confirm the effective default branch and other settings.

3. Read the core docs and this handoff by fetching and reading ASSISTANT_HANDOFF.md, WORKFLOWS.md, ARCHITECTURE_AND_SAFETY.md, and ASSISTANT_DOCS_AND_SNAPSHOTS.md.

4. Align with current work by reading open pull requests related to the controller or docs, reviewing their diffs and descriptions, and fetching any branches or issues that Joey references.

5. Adopt test-first and pull-request-first behavior by planning changes on a feature branch, using patch-based edits, running tests and linters, and then opening pull requests into main for Joey to merge.

## When documentation changes

The controller contract and Joey's expectations include a specific rule: when documentation for this project is updated and merged into the main branch, assistants must treat the new version as truth. After Joey says a pull request that updates docs has been merged into main and the branch deleted, assistants should re-fetch the updated documents, including this file and any docs in the docs directory, re-read them, and adjust their mental model accordingly. If there is any conflict between an older understanding and the newly merged docs, the merged docs win. This rule exists to avoid derailments where the human and assistant are talking past each other based on stale assumptions.

## Evolving this handoff document

This file is intentionally designed to be updated over time as the project, controller contract, and workflows evolve. When updating this document, use a feature branch, make patch-based edits to ASSISTANT_HANDOFF.md, update WORKFLOWS.md, ASSISTANT_DOCS_AND_SNAPSHOTS.md, or controller_contract in main.py if behavior or expectations change, run linters and tests as appropriate, and open a pull request into main. Future assistants should assume that the latest version of this file on main reflects the current truth about how to work on this repository, how to use the Adaptiv Controller, and how to stay in sync across sessions and chats.