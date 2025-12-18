# Adaptiv Controller – GitHub MCP Server

This repository is a self-hosted GitHub MCP (Model Context Protocol) server.
It exposes a safe, engineering-oriented tool surface so an assistant (for example a ChatGPT custom GPT) can work on GitHub repos using normal software practices: branches, diffs, tests/linters, and pull requests.

## Canonical operating model

**Roles**
- User (human): sets goals, reviews outcomes.
- Assistant (operator): runs tools, does the work, reports progress.

**Places**
- Remote repo: shared source of truth.
- Workspace: the assistant's PC (persistent clone on the service).
- Logs: user-facing status feed.

**Required phases**
Discovery -> Implementation -> Testing/verification -> Commit+push -> Summary

**Tool default**
Use `terminal_command` as the primary way to work (like a local dev machine). Higher-level workspace file tools exist for precise, deterministic edits.

## How to read this repo

There are two layers:

- **Engine (this repo)**: the MCP server + tool surface + safety model.
- **Controller (your ChatGPT assistant)**: the prompt and behaviors that decide *how* to use the tools.

Important role clarity:

- **The assistant uses the tools.** Humans do not “run commands”; the assistant does.
- When something fails, the assistant must decide whether it’s:
  - a **tool/engine issue** (this server),
  - a **GitHub issue** (auth, permissions, rate limiting),
  - or a **host/client issue** (ChatGPT/OpenAI tool-call layer).

This repo’s docs are the contract for how the engine behaves.

## Quick links

- Session startup protocol: `docs/start_session.md`
- Assistant session protocol: `docs/assistant/start_session.md`
- Assistant handoff: `docs/assistant/ASSISTANT_HANDOFF.md`
- Assistant playbook: `docs/assistant/ASSISTANT_HAPPY_PATHS.md`
- Operator workflows: `docs/human/WORKFLOWS.md`
- Operations runbook: `docs/human/OPERATIONS.md`
- Self-hosting (Render / general): `docs/human/SELF_HOSTED_SETUP.md`
- Self-hosting (Docker): `docs/human/SELF_HOSTING_DOCKER.md`
- Architecture & safety: `docs/human/ARCHITECTURE_AND_SAFETY.md`
- Tools reference: `Detailed_Tools.md`

## What the server provides

### GitHub tools

- Read: repository metadata, trees, files, issues/PRs, workflow runs, logs, search.
- Write (gated): branches, commits, PR creation/updates, comments, selected workspace actions.

### Workspace tools

Workspace tools operate in a persistent clone on the server (for example on Render):

- `ensure_workspace_clone`
- `terminal_command` *(formerly `run_command`; alias preserved)*
- `run_tests`, `run_lint_suite`, `run_quality_suite`
- `commit_workspace`, `commit_workspace_files`
- `workspace_self_heal_branch` (recover from a mangled workspace branch)

These are what make "act like a real engineer" possible: edit files, run tests/linters, debug CI, and keep changes reviewable.

### User-facing assistant logs (Render / stdout)

This server is designed so **Render logs feel like an assistant talking to the user**.

- `CHAT`: what the assistant would say in a normal chat (“Here’s what I’m doing next…”).
- `INFO`: concise progress updates and important decisions.
- `DETAILED`: deep diagnostics, tool parameters, and (bounded) file diffs.

For write tools that modify files, the server prints a **colored unified diff** at `DETAILED` level (green additions / red deletions), bounded by `WRITE_DIFF_LOG_MAX_LINES` and `WRITE_DIFF_LOG_MAX_CHARS`.

Related env vars:

- `LOG_LEVEL` (supports `CHAT` and `DETAILED` in addition to standard levels)
- `LOG_STYLE` (`plain` or `color`)
- `UVICORN_ACCESS_LOG` (enable/disable GET/POST access lines)

### Session logs (repo-local)

Assistants keep a durable per-repo log in `session_logs/`.

- Sessions are Markdown files like `session_logs/refactor_session_YYYY-MM-DD.md`.
- Commit/push helpers append a structured entry after successful workspace commits so “what happened” is visible in the repo history.

### Render integration

This server can optionally surface Render deployment context via tools:

- `list_render_logs` (reads Render logs; requires `RENDER_API_KEY` and an owner/workspace id)
- `get_render_metrics` (basic Render metrics)
- `render_cli_command` (executes the Render CLI; write-gated because it can deploy/restart)

Render env vars are documented in `.env.example`.

### Web browser tools

This server includes a small, assistant-usable web browser layer:

- `web_search` (DuckDuckGo HTML endpoint)
- `web_fetch` (fetch a URL with optional HTML-to-text extraction)

These tools exist to help assistants refresh documentation, chase down package behavior, and validate external facts.

## Quality suites (no runtime installs)

Runtime dependency installs are intentionally avoided. The service environment is prepared at deploy time.

- `scripts/run_lint.sh` should only lint/format-check.
- `scripts/run_tests.sh` should only run tests.

## Safety model in one page

Default posture:

- **Branch-first work**: do not develop directly on the default branch; use a feature branch and open a PR.
- **Write gate**: approvals should happen at remote-risk boundaries (push, web, Render CLI).
- **Auditability**: changes are committed to Git and reviewed via PRs.
- **Minimize payload risk**: prefer file slices over giant blobs; clamp command output when needed.

Controller mode override:

- For this repo (the live controller engine), you may intentionally run in **main-branch mode** when explicitly instructed.
  In that mode, treat every push as a production deploy: keep changes small, run quality gates locally, and confirm CI + redeploy before declaring success.

Details: `docs/human/ARCHITECTURE_AND_SAFETY.md` and `docs/human/WORKFLOWS.md`.

## Troubleshooting: “JSON errors” and tool-call failures

When you see “improperly coded JSON” or a tool call does not execute, treat it as one of these categories:

1. **Assistant constructed invalid tool args**
   - Fix: `describe_tool` → `validate_tool_args` → retry with corrected JSON.

2. **Client/host tool-call layer rejected the payload** (OpenAI/ChatGPT)
   - Symptoms: tool never runs; error is about formatting, message schema, or tool routing.
   - Fix: reduce payload size, avoid nested JSON-in-strings, validate JSON locally (`validate_json_string`), retry with minimal args.

3. **Server/tool error** (this repo)
   - Symptoms: tool runs but returns a structured error or a stack trace in logs.
   - Fix: follow the error context, check `/healthz`, then `validate_environment`.

4. **GitHub API error**
   - Symptoms: 401/403/422/429 or rate-limit messaging.
   - Fix: auth scopes, repo permissions, branch protections, retry/backoff.

## Health and observability

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, auth-present signal, in-memory metrics snapshot).
- `/sse` – MCP transport endpoint.
- `/static` – static assets (connector icons, branding).

Metrics are in-memory only (reset on restart) and never include secrets.

## License

License and commercial terms are intentionally documented separately.
See `licensing_plan.md` for a plain-language template.


- `docs/human/TERMS_AND_ROLES.md` — definitions for User vs Assistant/Operator; non-negotiable operating model.
