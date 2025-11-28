# Adaptiv Controller – GitHub MCP Server

> Self-hosted GitHub connector for ChatGPT, powering personal Adaptiv Controllers that you own and operate.

This repository contains the GitHub MCP server that powers the Adaptiv Controller experience. It is designed to be self-hosted by each user (for example on Render.com) and connected to their own ChatGPT account and GitHub credentials.

The controller itself (Joeys GitHub, officially the Adaptiv Controller) is a separate ChatGPT-side configuration and workflow layer that you sell. This repo is the backend GitHub connector the controller talks to.

---

## Canonical branch and development model

- main is the canonical, production branch.
  - All refactors, behavioral changes, and new tools are developed on feature branches.
  - Once changes are fully tested (including end-to-end smoke tests and documentation review), they are merged into main.
  - Temporary or refactor branches are deleted after merge.

- As a user of this project:
  - You should treat main as the source of truth.
  - Any feature branches are internal development branches and may be short-lived or experimental.

---

## What this project is

- A Model Context Protocol (MCP) server that exposes safe, high-level GitHub tools to ChatGPT.
- A self-hosted GitHub connector: each user deploys this server with their own GitHub token and runs it in their own infrastructure.
- A backend designed specifically to support the Adaptiv Controller pattern:
  - Strong write gating.
  - Branch-first workflows (no blind writes to main).
  - Patch-based edits for large files.
  - Clear verification after every write.
  - Optional workspace execution (run_command and run_tests) to run tests and commands from the controller.
  - Powerful search capabilities via GitHubs Search API, including public repositories.

What it is not:

- Not a hosted SaaS. You deploy and operate it yourself.
- Not the ChatGPT controller configuration. That is the Adaptiv Controller product you sell separately.

---

## For buyers (product view)

If you are purchasing this as a product:

- You are buying the Adaptiv Controller:
  - The controller configuration, workflows, and usage model inside ChatGPT.
  - The way the assistant uses the tools provided by this MCP server.

- You are not buying hosting or managed infrastructure:
  - You will deploy and operate this MCP server yourself (for example on Render.com).
  - You will supply and manage your own GitHub tokens and secrets.
  - You will decide which repos, branches, and environments the controller is allowed to touch.

In other words:

- You own the infrastructure and credentials.
- Adaptiv Controller tells your assistant how to use the tools safely and effectively.

---

## Naming and branding

There are three relevant names:

1. Adaptiv Controller (official product name)
   - This is your commercial controller concept and brand.
   - It describes the way ChatGPT uses this MCP server to interact with GitHub safely.

2. Custom controller name in ChatGPT
   - Each user is free to name their ChatGPT controller anything they like (for example My GitHub Copilot, Studio GitHub, Joeys GitHub).
   - Internally, any controller that uses this server and follows the documented workflows is considered an Adaptiv Controller under your license and brand, regardless of the display name in ChatGPT.

3. This repository (Proofgate-Revocations/chatgpt-mcp-github)
   - This is the GitHub MCP server implementation used by Adaptiv Controllers.
   - It can also be used by other controllers or assistant prompts, as long as they respect the safety and write-gating model.

---

## High-level architecture

At a high level, the flow looks like this:

ChatGPT Assistant (Adaptiv Controller)
    |
    |  MCP tool calls (read or write)
    v
GitHub MCP Server (this repo, self-hosted)
    |
    |  GitHub REST / GraphQL / Search APIs
    v
GitHub (your repos, branches, PRs, and public code)

Key properties:

- The user owns and hosts the MCP server (for example on Render.com).
- The user supplies their own GitHub token and configuration.
- The controller in ChatGPT only orchestrates tool calls; it never stores secrets and has no direct network access to GitHub.

---

## Safety and write gating

This server is designed around a strict safety model:

- Tools are registered via a custom mcp_tool decorator that:
  - Tags tools as read or write.
  - Sets meta.write_action and meta.auto_approved.
  - Sets ToolAnnotations.readOnlyHint appropriately.

- A global WRITE_ALLOWED flag gates all destructive operations:
  - Controlled at runtime by the authorize_write_actions tool.
  - When WRITE_ALLOWED is false, write-tagged tools raise WriteNotAuthorizedError.

- High-level orchestrations always follow this pattern:
  1. Ensure you are on a safe branch (no direct writes to main).
  2. Perform the write (commit, PR creation, deletion, and similar).
  3. Verify the change via read-after-write and SHA comparison.
  4. Only then proceed (for example open or merge a PR).

Representative tools already implemented:

- Read and inspect
  - get_file_contents, get_file_slice, fetch_files, list_repository_tree.
  - Issue and PR readers: fetch_issue, fetch_pr, fetch_pr_comments, get_pr_diff, get_pr_info, reactions, and similar.
  - Workflow readers: list_workflow_runs, get_workflow_run, list_workflow_run_jobs, get_job_logs.
  - build_unified_diff for human and machine readable patches.
  - Global search via GitHub Search API:
    - search supports code search, repo search, issues or PR search, and commit search.
    - It can operate across public GitHub repositories and private repositories that the token can access.
    - This allows Adaptiv Controller to discover examples and patterns in public code, search your own orgs codebase, and cross-reference issues and PRs at scale.

- Write and orchestration
  - apply_text_update_and_commit for single-file text edits with verification and diff.
  - apply_patch_and_commit for patch-based edits via unified diffs.
  - update_files_and_open_pr for multi-file commit plus verify plus PR.
  - Branch and PR helpers: ensure_branch, create_branch, create_pull_request, merge_pull_request, close_pull_request, comment_on_pull_request.
  - Extra tools in extra_tools.py: delete_file, delete_remote_branch, and similar.

All write tools are explicitly tagged as write actions and require WRITE_ALLOWED to be enabled.

---

## Workspace execution: run_command and run_tests

Beyond direct GitHub API operations, the server exposes powerful workspace tools that allow the controller (with the users permission) to run commands against a real checkout of the repository:

- run_command
  - Clones the repo at a given ref into a temporary workspace.
  - Optionally applies a unified diff patch before execution.
  - Optionally creates a temporary virtual environment (use_temp_venv) so the assistant can install Python dependencies with pip install and run arbitrary commands such as linters, migrations, or scripts.
  - Enforces a configurable timeout and returns stdout, stderr, exit code, and truncation flags once output truncation is wired in.

- run_tests
  - A focused wrapper around run_command for running test commands.
  - Same workspace and venv behavior, but with test-oriented defaults such as pytest and a longer timeout.

These tools enable extremely high-level workflows, for example:

- Create a feature branch, apply a patch, install missing dependencies, run tests, and open a PR only if tests pass.
- Run type checking or linting on a proposed change, summarize failures, and suggest fixes.

Important points:

- These tools are write-tagged and gated by WRITE_ALLOWED.
- They run in the users own Render-hosted environment using the users repository and tokens.
- The controller should always ask explicit permission before running commands or installing dependencies, and prefer safe branches and smoke-test branches for invasive operations.

---

## Custom flows and adaptivity

The server is intentionally tool-centric. It provides a rich, well-documented tool surface that any assistant can use to build higher-level workflows.

This enables the Adaptiv part of Adaptiv Controller:

- Each user can define their own controllers or GPTs in ChatGPT, evolve their own prompts and instructions over time, and teach their assistants to favor certain workflows (for example always open a PR, never push to main, always run tests with run_tests before merging, and use search to consult public code patterns before making changes).

- Regardless of the custom controller name they choose, if it connects to this MCP server, respects the documented safety model, and uses the provided tools and orchestrations, then it is effectively an Adaptiv Controller instance in terms of capabilities and behavior.

Your commercial product is the controller design and workflows layered on top of this tool surface.

---

## Deployment model (self-hosted)

Typical deployment for an end user:

1. Host the MCP server
   - Fork or clone this repository.
   - Deploy to Render.com or another hosting platform as a Python web service.
   - Configure environment variables, for example GitHub tokens, optional auto approval flags, concurrency limits, and HTTP timeouts.
   - Start the app (for example via uvicorn) and confirm health.

2. Connect ChatGPT to the MCP server
   - Add a custom MCP integration in ChatGPT pointing at the deployed server.
   - Sanity-check the connection using get_server_config, list_all_actions, and ping_extensions.

3. Create a controller (Adaptiv Controller instance)
   - In ChatGPT, create a new custom assistant or GPT.
   - Paste or import the Adaptiv Controller system prompt and configuration you provide.
   - Give it any display name they like.
   - The controller then calls the tools exposed by this MCP server to operate on their GitHub repos and search across public GitHub when appropriate.

You do not host or manage their deployment; you supply the controller logic and documentation that explains how to do this safely.

---

## Status and roadmap (server-side)

On main (after refactor merge):

- Implemented:
  - Patch-based write flow: apply_patch_and_commit.
  - Text-based write flow: apply_text_update_and_commit.
  - Multi-file PR orchestration: update_files_and_open_pr.
  - Extra tools for file deletion and branch cleanup.
  - list_all_actions with a global tool registry including extension tools.
  - Strong write gating via authorize_write_actions and WRITE_ALLOWED.
  - Workspace commands: run_command, run_tests.
  - Search via GitHub Search API (search tool) across public and private repositories, subject to token permissions.

- Planned or in progress:
  - Output truncation in run_command and run_tests (stdout and stderr size limits with truncation flags).
  - Stricter branch defaults for low-level write tools (avoiding implicit writes to main).
  - Issue and project write tools (create or update issues, label management, and similar).
  - Documentation set:
    - Self-hosted setup guide for end users.
    - Architecture and safety model for advanced users.
    - Workflow guide for common Adaptiv Controller scenarios.
    - Guidance for keeping assistant-facing documentation and snapshots up to date (for example how to maintain design docs, changelogs, and source-of-truth notes that the controller can reference).

---

## Licensing and brand notes

- Adaptiv Controller is the name for your controller concept and product.
- Controllers created by end users may have any display name in ChatGPT, but they are expected to respect your usage guidelines and license, and they are functionally instances of the Adaptiv Controller pattern when built against this MCP server.

The specific license terms for this repository and the Adaptiv Controller configuration are determined by you and should be documented separately, for example in a LICENSE file and in commercial agreements.

---
