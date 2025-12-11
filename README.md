<p align="center">
  <img src="assets/logo/adaptiv-logo.png" alt="Adaptiv Controller logo" width="200" />
</p>

Adaptiv Controller uses this server to talk to GitHub. You deploy it yourself (for example on Render.com), provide your own GitHub token, and connect it to ChatGPT as an MCP server.

Assistants are expected to treat this controller like their own development machine—lean on `run_command`/`run_tests` for execution, quick searches, and usage checks, and avoid large, token-heavy inline detours (for example huge heredocs or full-file dumps) when a concise command, slice, or diff keeps context tight. This server does not add its own per-task budgets beyond what OpenAI and GitHub already enforce; instead it defines workflows, guardrails, and editing preferences inside those external limits.

## What this server does

At a high level, this MCP server:

Adaptiv Controller is designed for **customers who want a safe, self-hosted GitHub AI controller** rather than a hosted black box. Typical buyers and users include:

- Solo developers and very small teams who want an AI engineer that works the way they do, across all of their repositories.
- Engineering leaders who want a repeatable, auditable way for AI to open PRs, run tests, and refactor code without bypassing existing review and branch policies.
- Safety-conscious teams (fintech, infra, security, regulated industries) who need tight control over credentials, infrastructure, and change policies.

In this model:

- This repository is the **engine** – a hardened GitHub MCP server you run in your own infrastructure.
- Your Adaptiv Controller configuration (for example a custom GPT like "Joey's GitHub") is the **product** you sell: the prompts, policies, and workflows that teach the AI how to use this engine safely.

You can deploy one instance per customer, or share a hardened deployment across multiple internal teams, depending on your licensing and operational model.
---

## What this project is

- A Model Context Protocol (MCP) server that exposes safe, high-level GitHub tools to ChatGPT.
- A self-hosted GitHub connector: each user deploys this server with their own GitHub token and runs it in their own infrastructure.
- A backend designed specifically to support the Adaptiv Controller pattern:
  - Strong write gating.
  - Changes flow through feature branches (no blind writes to main).
  - Patch-based edits for large files.
  - Clear verification after every write.
  - Optional workspace execution (run_command and run_tests) to run tests and commands from the controller.
  - Powerful search capabilities via GitHubs Search API, including public repositories.

What it is not:

- Not a hosted SaaS. You deploy and operate it yourself.
- Not the ChatGPT controller configuration. That is the Adaptiv Controller product you sell separately.

---

## Product overview (for customers)

If you are buying this as a product, you are buying the **Adaptiv Controller GitHub Kit** – a self-hosted controller, not a hosted SaaS. Think of it as a controllable AI teammate that lives inside your own GitHub and infrastructure.

With this kit you get:

- A self-hosted GitHub MCP server (this repo):
  - Runs in your own environment (Render, VM, Kubernetes, etc.).
  - Uses your GitHub token(s) and respects your repo and branch protections.
  - Exposes a curated set of GitHub tools (read/write) over MCP.

- Controller workflows and prompts (your product layer):
  - Recommended controller prompts and workflows that teach the AI to always work on feature branches, run tests, and open PRs instead of pushing directly to `main`.

- Clear separation of responsibilities:
  - **You** own and evolve the controller prompts, policies, and workflows you sell to customers.
  - **Your customers** own hosting, credentials, and which repositories/branches the controller is allowed to use.

This design keeps credentials and source code access entirely under the customer’s control while still giving them a powerful AI collaborator on their GitHub activity.
---

## Quickstart

Here is a minimal end-to-end flow for running Adaptiv Controller as your personal AI developer:

1. **Deploy the MCP server on Render.com**
   - Fork or clone this repository, or unpack a versioned bundle (for example `adaptiv-controller-v0.1.0.tar.gz`).
   - Create a new Render web service and point it at this repository or bundle.
   - Configure required environment variables (GitHub token, controller repo, default branch, timeouts, and similar) using `docs/human/SELF_HOSTED_SETUP.md`.
   - Wait for Render to deploy and confirm `/healthz` reports status ok.

2. **Connect ChatGPT to the server**
   - In ChatGPT, add an MCP integration pointing at your Render deployment.
   - In a fresh session, ask the assistant to call `validate_environment` and `get_server_config` so it understands the live configuration.

3. **Create or update your Adaptiv Controller assistant**
   - Create a custom GPT or assistant that uses this MCP server.
   - Seed it with the current controller prompt from `docs/assistant/CONTROLLER_PROMPT_V1.md`.
   - Optionally create or update `docs/adaptiv/preferences.md` to capture your personal coding and workflow preferences; teach the assistant to read and respect those preferences at startup.

4. **Run a smoke-test workflow**
   - Ask the assistant to follow the documented branch / diff / test / PR flow on a small, low-risk change.
   - Verify that it:
     - Creates a feature branch (never writes directly to `main`).
     - Uses patch-based edits where appropriate.
     - Runs tests or a quality suite before opening a PR.
     - Opens a PR for you to review instead of merging on its own.

5. **Iterate and adapt**
   - As you see how the assistant behaves, update your controller prompt and `docs/adaptiv/preferences.md` to better reflect your style.
   - The MCP server stays stable; your controller logic and preferences evolve over time.

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

## Code organization

Shared infrastructure now lives in the `github_mcp/` package so the main entrypoint stays focused on tool definitions:

- `config.py` centralizes environment-driven settings and logging setup.
- `metrics.py` holds the in-process metrics registry used by tool logging and health checks.
- `http_clients.py` and `github_content.py` contain HTTP client helpers and GitHub content utilities.
- `workspace.py` wraps persistent workspace management and shell execution helpers.

The `main.py` module imports these helpers and re-exports the existing tool surface so controllers and tests continue to use the same interface while the implementation is easier to maintain.

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
  - Extra tools in `extra_tools.py`: delete_file, update_file_from_workspace, update_file_sections_and_commit, build_section_based_diff, get_file_slice, get_file_with_line_numbers, and apply_line_edits_and_commit for token-thrifty edits.
- JSON helper: validate_json_string to sanity-check and normalize JSON strings before returning them to clients or feeding them into other tools, including pretty-print output and line-aware error pointers for fast repairs. Controllers should treat this as an automatic pre-flight step for any non-trivial JSON they emit so assistants do not have to remember to call it manually.
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
- `validate_json_string`: validate and normalize JSON output, especially for long payloads such as sections arrays used with `build_section_based_diff`; includes a copy-ready pretty version plus line-level error snippets and pointers when parsing fails. Assistants should consider this a default part of their JSON hygiene routine so responses and tool payloads are validated before they leave the controller.

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

- Most write-tagged tools are gated by WRITE_ALLOWED, but workspace setup and non-mutating commands are allowed without a toggle; set ``installing_dependencies=true`` (or disable the temp venv) when you need gating to cover installs or other server mutations.
- They run in the users own Render-hosted environment using the users repository and tokens.
- The controller should always ask explicit permission before mutating GitHub state or installing dependencies, and prefer safe branches and smoke-test branches for invasive operations.

When behavior feels surprising or tools appear to be missing, controllers and assistants should call meta tools before assuming a bug:

- `get_server_config`: Inspect write gating, default branches, and controller repo configuration.
- `list_all_actions`: Inspect the full set of tools currently exposed by this MCP server.
- `list_write_tools`: Focus on the subset of tools that can modify state.
- `validate_environment`: Check for missing tokens, misconfigured controller repo/branch, or unsafe timeout/concurrency settings.
- `ping_extensions`: Confirm that extra_tools.py and any other extensions have been loaded.
- Documentation in `docs/`: Protocols, prompts, and workflows for controllers.

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
   - Fork or clone this repository, or unpack a versioned bundle (for example `adaptiv-controller-v0.1.0.tar.gz`) as described in `docs/DISTRIBUTION.md`.
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

This repository includes a documentation set under `docs/`:

- `docs/human/` – operator and buyer docs:
  - `ARCHITECTURE_AND_SAFETY.md` – internal architecture and safety model.
  - `SELF_HOSTED_SETUP.md` and `SELF_HOSTING_DOCKER.md` – deployment and configuration guides for customer environments.
  - `OPERATIONS.md` – runbook for incidents and common failures.
  - `WORKFLOWS.md` – recommended operational workflows for humans running the kit.
  - `UPGRADE_NOTES.md` – versioning, upgrade, and rollback guidance.
  - `DISTRIBUTION.md` and `BRANDING.md` – how you package, brand, and ship the kit to customers.
  - `pr-flow-test-adaptiv-pr-check.md` – example CI configuration for PR flows.

- `docs/assistant/` – controller/assistant docs:
  - `ASSISTANT_HANDOFF.md` – high-level expectations for assistants attaching to this controller.
  - `ASSISTANT_DOCS_AND_SNAPSHOTS.md` – guidance for keeping prompts, snapshots, and docs aligned with reality.
  - `ASSISTANT_HAPPY_PATHS.md` – concrete routines for branch, diff, test, and PR flows.
  - `CONTROLLER_PROMPT_V1.md` – copy-pasteable system prompt for controllers built on this kit.
  - `start_session.md` – startup sequence and bootstrapping protocol for new assistant sessions.

- `docs/adaptiv/` – optional per-install preferences and product flavoring:
  - `preferences.md` – structured but flexible document where each user or customer can record coding style, branch and PR habits, testing expectations, and communication preferences for their Adaptiv Controller assistant.

Documentation in this repository is the source of truth for how controllers and assistants should interact with the server. Keep prompts and workflows aligned with these docs instead of duplicating stale assumptions.
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
  - Changes flow through feature branches (no direct writes to `main`).
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