<p align="center">
  <img src="assets/logo/adaptiv-logo.png" alt="Adaptiv Controller logo" width="200" />
</p>

# Adaptiv Controller – GitHub MCP Server

> Self-hosted GitHub MCP server that lets ChatGPT act as a safe, policy-driven engineer on your repositories.

Adaptiv Controller uses this server to talk to GitHub. You deploy it yourself (for example on Render.com), provide your own GitHub token, and connect it to ChatGPT as an MCP server. The server publishes a versioned controller contract via the `controller_contract` tool; controllers should read that contract instead of hard-coding assumptions or duplicating it in prompts.

Adaptiv Controller (for example "Joeys GitHub") lives entirely on the ChatGPT side as a custom assistant and workflow layer. This repository is the backend GitHub connector that controller instances use.

---

## Who this is for (personal controller view)

Adaptiv Controller is designed first for **individual developers and very small teams** who want a personal, self-hosted GitHub controller instead of a vendor-hosted agent. Typical use cases:

- You want ChatGPT (or another MCP host) to behave like **your** engineer over time, tuned to your repositories and habits.
- You are comfortable deploying a small Python service (for example on Render.com, a VM, or a container platform).
- You prefer to keep your GitHub tokens and repo access fully under your own control.

In this model:

- This repository is the **engine** – a stable, safety-focused GitHub MCP server you run yourself.
- Your ChatGPT controller (for example "Joey’s GitHub") is the **personality and workflow layer** – where you express personal preferences, style, and working habits.

You can absolutely use this kit in larger teams, but 1.0 is intentionally optimized so a single developer can fork the repo, deploy the server, and evolve their own controller prompt over time without needing enterprise-scale infrastructure.

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

If you are buying this as a product, you are buying the **controller**, not a hosted service.

- You get the Adaptiv Controller:
  - The controller configuration, workflows, and usage model inside ChatGPT.
  - The way the assistant uses the tools exposed by this MCP server.

- You are responsible for infrastructure:
  - Deploying and operating this MCP server yourself (for example on Render.com or your own VM).
  - Supplying and managing your own GitHub tokens and secrets.
  - Deciding which repos, branches, and environments the controller is allowed to touch.

In short:

- You own the infrastructure and credentials.
- Adaptiv Controller tells your assistant how to use the tools safely and effectively.

If you are a solo developer or a small team, you can treat this kit as a **personal GitHub controller**:

- The MCP server stays conservative and safety-focused.
- Your controller prompt is where you teach the assistant your own style (branch naming, how aggressively to refactor, how much explanation you want, and so on).

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
  - Diff helpers: build_unified_diff and build_section-based diff for building patches server-side from full content or line-based sections.
  - Extra tools in extra_tools.py: delete_file, delete_remote branch, and similar.
  - JSON helper: validate_json_string to sanity-check and normalize JSON strings before returning them to clients or feeding them into other tools.

All write tools are explicitly tagged as write actions and require WRITE_ALLOWED to be enabled.

### Write tools

- `apply_patch_and_commit`: apply a unified diff to one or more files and commit.
- `update_files_and_open_pr`: multi-file update + PR orchestration.
- `apply_text_update_and_commit`: full-file replacement helper for single-file updates.
  - Prefer patch-based helpers for code changes (`build_unified_diff` +
    `apply_patch_and_commit` or `update_files_and_open_pr`).
  - This helper stays available for simple docs/config edits when a full-file replace
    is acceptable and WRITE_ALLOWED is enabled.
- `build_section_based_diff`: construct a patch for large files by specifying line-based sections to replace, then apply it with `apply_patch_and_commit`.
- `validate_json_string`: validate and normalize JSON output, especially for long payloads such as sections arrays used with `build_section_based_diff`.

- ensure_workspace_clone
  - Ensure a repo/ref workspace exists on disk and optionally reset it to the remote branch.

- run_command
  - Clones the repo at a given ref into a persistent workspace on disk.
  - Optionally applies a unified diff patch before execution.
  - Optionally creates a persistent virtual environment (use_temp_venv) so the assistant can install Python dependencies with pip install and run arbitrary commands such as linters, migrations, or scripts.
  - Enforces a configurable timeout and returns stdout, stderr, exit code, and truncation flags once output truncation is wired in.
  - Reuses the same workspace between calls so dependencies and edits stick around until explicitly reset.

- commit_workspace
  - Stages, commits, and optionally pushes changes from the persistent workspace to the effective branch.
  - Useful when run_command or run_tests workflows make edits that need to be saved or published.

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

When behavior feels surprising or tools appear to be missing, controllers and assistants should call meta tools before assuming a bug:

- `get_server_config`: Inspect write gating, default branches, and controller repo configuration.
- `list_all_actions`: Inspect the full set of tools currently exposed by this MCP server.
- `list_write_tools`: Focus on the subset of tools that can modify state.
- `validate_environment`: Check for missing tokens, misconfigured controller repo/branch, or unsafe timeout/concurrency settings.
- `ping_extensions`: Confirm that extra_tools.py and any other extensions have been loaded.
- `controller_contract`: Read the versioned contract that describes expectations between controllers, assistants, and this MCP server.

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
   - Start the app (for example via uvicorn) and confirm health by:
     - Hitting `GET /healthz` on your deployment URL to verify status, uptime, token presence, and a small metrics snapshot.
     - Optionally calling `get_server_config` and `validate_environment` from ChatGPT to confirm configuration.

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

## Observability and health checks

The MCP HTTP server exposes a small set of HTTP endpoints:

- `/` – plain-text home message that confirms the server is running and reminds you to connect ChatGPT to `/sse`.
- `/sse` – SSE endpoint used by the MCP transport.
- `/healthz` – JSON health check intended for uptime probes and lightweight diagnostics.

The `/healthz` response is intentionally small and stable. It includes:

- `status`: `\"ok\"` when the process is healthy.
- `uptime_seconds`: seconds since the server process started.
- `github_token_present`: boolean indicating whether a GitHub token is configured.
- `controller.repo` and `controller.default_branch`: the controller repository and default branch currently in use.
- `metrics`: an in-process metrics snapshot with:
  - Per-tool counters (`calls_total`, `errors_total`, `write_calls_total`, `latency_ms_sum`).
  - Aggregate GitHub client counters (`requests_total`, `errors_total`, `rate_limit_events_total`, `timeouts_total`).

Metrics are kept in memory only; they reset on process restart and never include full payloads, secrets, or user content.

---

## Documentation and workflows

This repository includes (or will include) a small docs set under `docs/` to keep behavior clear and assistant-friendly:

- `docs/SELF_HOSTED_SETUP.md` – deployment and configuration guide for operators (see issue #128).
- `docs/ARCHITECTURE_AND_SAFETY.md` – internal architecture and safety model (see issue #129).
- `docs/WORKFLOWS.md` – recommended end-to-end workflows for assistants and advanced users.
- `docs/ASSISTANT_DOCS_AND_SNAPSHOTS.md` – guidance for keeping prompts, snapshots, and docs aligned with reality.

Assistants should use these docs together with the live tool list to design safe, repeatable flows for their own Adaptiv Controller instances.

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
  - HTTP `/healthz` endpoint exposing a JSON health payload (status, uptime, token presence, controller configuration, and a metrics snapshot).
  - In-process metrics registry for MCP tool calls and GitHub client requests (counters and latency sums surfaced via `/healthz`).

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

## Product: Adaptiv Controller GitHub Kit

The Adaptiv Controller GitHub Kit is a self-hosted GitHub AI controller you run in your own infrastructure. It turns an LLM (for example ChatGPT with MCP) into a safe, policy-driven collaborator on your repositories, without giving any third-party hosted agent direct access to your code.

### What this kit does

- Exposes a high-level GitHub tool surface over MCP:
  - Read: files, trees, issues, PRs, workflow runs, logs, search (code/issues/commits/repos).
  - Write (gated): branches, commits, patches, PRs, comments, and selected workspace commands.
- Implements opinionated safety controls:
  - Branch-first workflows (no direct writes to `main`).
  - Central write gate that must be explicitly enabled per session.
  - Optional per-repo and per-branch write policies.
  - Optional tool- and command-level allowlists/denylists.
- Provides ops and observability hooks:
  - `/healthz` endpoint with token presence, controller config, and metrics snapshot.
  - Structured logging for tool calls and GitHub API usage.
  - Workspace timeouts and concurrency controls.

You connect this MCP server to a controller (prompt plus configuration) in ChatGPT or another MCP-capable host. The controller decides how to use the tools; this kit guarantees what is possible and how safely it can be done.

### Who this is for

This kit is designed for:

- Developers and small teams who want an AI helper that can:
  - Open real PRs.
  - Run tests and linters.
  - Work across multiple repos.
  without handing full write access to a vendor-hosted agent.
- Safety-conscious teams (fintech, infra, security, and similar) that:
  - Need self-hosted infrastructure.
  - Want explicit and auditable policies around what the AI can change.
  - Prefer to own and evolve their own prompts/controllers over time.

It is not a hosted SaaS. You deploy it, you configure it, and you control it.

### What you get in this kit

When you adopt the Adaptiv Controller GitHub Kit, you get:

- A self-hosted MCP server implementation:
  - Python web service (FastAPI/FastMCP) ready to run on Render, a VM, or a container platform.
  - High-level tools for reading/writing repos, issues, PRs, and running workspace commands.
- A versioned controller contract:
  - Machine-readable description of the tool surface and safety expectations.
  - Stable contract the controller can read instead of hard-coding assumptions.
- Safety and configuration model:
  - Global write gate (`WRITE_ALLOWED`) with an explicit authorization tool.
  - Env- or config-driven policies for repos, branches, tools, and commands.
  - Workspace limits (timeouts, concurrency) for `run_command` / `run_tests`.
- Documentation:
  - Self-hosted setup and upgrade guidance.
  - Architecture and safety model.
  - Recommended workflows for controllers and advanced users.
  - Operations/runbook notes (health checks, common failure modes).

This is a controller kit: a hardened base you can fork, extend, and adapt to your environment.

### What you are responsible for

As an operator or buyer:

- You host and operate the MCP server:
  - Choose a hosting platform (Render, your own VM, container stack, and similar).
  - Configure environment variables and secrets (GitHub tokens, policies, timeouts).
  - Monitor logs and `/healthz` according to your own standards.
- You control the safety envelope:
  - Decide which repos and branches the AI is allowed to touch.
  - Decide which tools and commands are enabled in your deployment.
- You own the controller behavior:
  - Create and maintain your own controller(s) in ChatGPT or another MCP host.
  - Decide how conservative or aggressive the assistant should be.
  - Update prompts and policies over time as your team’s needs change.

This kit deliberately avoids any phone-home or central control: after installation, you are in full control of both infrastructure and policy.

### Licensing and plans

Licensing for this kit is intended to be simple and self-service. A separate document, `licensing_plan.md`, outlines suggested tiers (for individuals, small teams, and larger organizations) and what is included in each. You can adapt those terms to your own pricing and commercial model.

At a high level:

- All plans are self-hosted: you run the MCP server and supply your own GitHub tokens and infrastructure.
- You are free to customize and extend the kit internally, subject to the license terms you configure for your use.

See [licensing_plan.md](./licensing_plan.md) for a customizable template of licensing tiers and options.