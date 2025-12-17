# Proof of concept (historical)

This file documents the original “controller-in-a-box” proof of concept: prove that an assistant can reliably do real engineering work via **GitHub + a persistent workspace**, with high-quality, user-facing logs.

The project has evolved since the first prototype. Tool names and flows in this document are kept in sync with the current engine.

## What the PoC needed to prove

1. **Read** GitHub content reliably (files, issues, PRs, workflows).
2. **Edit** files safely and audibly (verification, diffs, no silent truncation).
3. **Run** local commands in a persistent workspace (`terminal_command`).
4. **Commit + push** changes back to GitHub (`commit_workspace`, `commit_workspace_files`).
5. **Validate quality** (tests + lint) before shipping.
6. **Explain progress** in logs as if the assistant is talking to the user.

## Current “minimal end-to-end” happy path

1. Ensure a feature branch exists:
   - `ensure_branch`
2. Ensure a workspace clone exists:
   - `ensure_workspace_clone`
3. Make a change locally (workspace):
   - `terminal_command` (edit files with normal tools)
4. Commit + push:
   - `commit_workspace` (or `commit_workspace_files`)
5. Run quality gates:
   - `run_tests` / `run_lint_suite` / `run_quality_suite`
6. Open a PR:
   - `open_pr_for_existing_branch` (or `create_pull_request`)

## Why this repo matters

This repository is not a “wrapper around GitHub.” It is a controller engine:

- The tool surface is designed for assistants.
- The logging is designed for humans.
- The workflow is designed to feel like a coworker pairing session.

If the PoC stops being true (for example, logs become unreadable, quality gates drift, or tool schemas become unreliable), treat it as a regression.
