# Adaptiv Controller – GitHub MCP Server

This repository is a self-hosted GitHub MCP (Model Context Protocol) server.
It exposes a safe, engineering-oriented tool surface so an assistant (for example a ChatGPT custom GPT) can work on GitHub repos using normal software practices: branches, diffs, tests/linters, and pull requests.

## How to read this repo

There are two layers:

- **Engine (this repo)**: the MCP server + tool surface + safety model.
- **Controller (your ChatGPT assistant)**: the prompt and behaviors that decide *how* to use the tools.

Important role clarity:

- **The assistant uses the tools.** The human user does not “run the controller” or execute MCP actions.
- When something fails, the assistant must decide whether it’s:
  - a **tool/engine issue** (this server),
  - a **GitHub issue** (auth, permissions, rate limiting), or
  - a **host/client issue** (ChatGPT/OpenAI tool-call layer).

This repo’s docs are the contract for how the engine behaves.

## Quick links

- Session startup protocol: `docs/start_session.md`
- Assistant handoff: `docs/assistant/ASSISTANT_HANDOFF.md`
- Assistant playbook: `docs/assistant/ASSISTANT_HAPPY_PATHS.md`
- Operator workflows: `docs/human/WORKFLOWS.md`
- Self-hosting (Render / general): `docs/human/SELF_HOSTED_SETUP.md`
- Self-hosting (Docker): `docs/human/SELF_HOSTING_DOCKER.md`
- Architecture & safety: `docs/human/ARCHITECTURE_AND_SAFETY.md`
- Tools reference: `Detailed_Tools.md`

## What the server provides

### GitHub tools

- Read: repository metadata, trees, files, issues/PRs, diffs, workflow runs, logs, search.
- Write (gated): branches, commits, patches, PR creation/updates, comments, selected workspace actions.

### Workspace tools

Workspace tools operate in a persistent clone on the server (for example on Render):

- `ensure_workspace_clone`
- `run_command`
- `run_tests`, `run_lint_suite`, `run_quality_suite`
- `commit_workspace`, `commit_workspace_files`

These are what make “act like a real engineer” possible: install deps, run tests, debug CI, and keep changes reviewable.

## Safety model in one page

- **Branch-first work**: do not develop directly on the default branch; use a feature branch and open a PR.
- **Write gate**: tools tagged as write actions are controlled by `WRITE_ALLOWED` and `authorize_write_actions`.
- **Auditability**: changes are committed to Git and reviewed via PRs.
- **Minimize payload risk**: prefer file slices and diffs over giant blobs; clamp command output when needed.

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
   - Fix: token scopes, repo permissions, branch protections, retry/backoff.

Operator checklist for any report of “tools are missing” or “it’s acting weird”:

- `get_recent_tool_events(limit=50, include_success=false)`
- `get_server_config`
- `list_all_actions(include_parameters=true)`
- `validate_environment`
- `/healthz`

## Health and observability

The server exposes:

- `/healthz` – small JSON health payload (uptime, controller defaults, token-present signal, in-memory metrics snapshot).
- `/sse` – MCP transport endpoint.

Metrics are in-memory only (reset on restart) and never include secrets.

## License

License and commercial terms are intentionally documented separately.
See `licensing_plan.md` for a plain-language template.
