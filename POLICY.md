# Controller policy (single source of truth)

This file is the *only* authoritative document for:

- How this controller behaves.
- What the controller can and cannot do.
- The user’s preferences that assistants must follow when operating this controller.

If anything in this repository conflicts with this file, **this file wins**. Any other documentation should only **link** to this file and must not redefine behavior.

---

## Scope

This repository is a self-hosted GitHub MCP (Model Context Protocol) server (“the controller”). It exposes tools that allow an AI assistant to:

- Read and search GitHub repositories.
- Maintain a persistent workspace clone (“Render/workspace clone”) for editing and running tests/linters.
- Create branches, commit changes, and open pull requests.

The controller is designed to support normal software practices (branches, diffs, tests/linters, PRs) while enforcing **user-controlled write gating** and **UI approval prompts** for hard writes.

---

## Definitions

### Workspace clone vs GitHub API

- **Workspace clone**: the local repository clone used for editing files, running tests/linters, and generating commits.
- **GitHub API state**: the remote GitHub repository state.

**Source of truth rule:** the workspace clone is the operational truth while changes are being prepared. GitHub becomes aligned only after pushing commits/branches.

### Tool side effects

Tools are categorized for UI prompting purposes:

- **READ_ONLY**: no mutations.
- **LOCAL_MUTATION**: local-only operations (workspace edits, running commands, etc.). These should **not** create noisy UI approval prompts.
- **REMOTE_MUTATION** (“hard writes”): operations that mutate GitHub state (creating/updating/deleting files, branches, PRs, merges, etc.). These must **always** require explicit UI approval.

---

## Write gate and approvals

### Hard writes must always prompt

**REMOTE_MUTATION tools must always trigger a UI approval prompt.** This is non-negotiable.

### Soft writes are controlled by a write gate

The user controls whether write actions are enabled using an environment variable in Render:

- `GITHUB_MCP_WRITE_ALLOWED` (boolean; default: `true`)

When write actions are disabled (`false`), the controller should block tool execution for any tool that performs a write that is controlled by the gate.

### Toggle tool (user confirmation)

The controller provides a tool to toggle the gate after the user explicitly confirms:

- `authorize_write_actions(approved=true|false)`

Assistants must never toggle writes on without an explicit user instruction.

---

## UX policy for prompts

The user explicitly prefers:

1. **Hard writes (REMOTE_MUTATION) must always prompt for approval.**
2. **Local mutation tools should not prompt.**
3. The assistant must avoid behavior that causes “prompt for everything”.

The controller must keep connector-facing tool metadata consistent with this policy (e.g., correct `write_action` and side-effect metadata).

---

## Operational expectations for assistants

### Branching and PR hygiene

When making changes:

- Work on a **fresh branch**.
- Run **tests and linters** (at minimum `pytest` and `ruff`) before pushing.
- Open a PR with a **detailed summary** of changes and how they were verified.

### Dependency installation

- Only install dependencies when needed.
- If new dependencies are required for the project, they must be added to `dev-requirements.txt`.

### Token/verbosity discipline

- Avoid excessive terminal output (large outputs can cause tool disconnects).
- Prefer targeted commands and capped output (e.g., `head`, `tail`, `rg | head`).

### Render vs GitHub

- Render is used for **health/stats and workspace execution**.
- The controller’s runtime behavior is defined by **code in this GitHub repository**.

---

## Diagnostics and logging policy

Diagnostics must support debugging without corrupting or obscuring the underlying error.

### Redaction

- Redaction must remove known secret formats.
- Redaction must not broadly erase non-secret identifiers (e.g., commit SHAs, ids).

### Optional diagnostics

The following env vars control diagnostics behavior:

- `GITHUB_MCP_DIAGNOSTICS` (default: `true`) — when `false`, suppresses noisy exception logging.
- `GITHUB_MCP_RECORD_RECENT_EVENTS` (default: `true`) — when `false`, disables the in-memory recent tool event buffer.

---

## Non-goals

- CI may not exist for this repository. The assistant must run tests/linters manually.
- The controller does not guarantee that external CLI tools (e.g., `gh`) are installed in the workspace image.

---

## Appendix: environment variables

- `GITHUB_MCP_WRITE_ALLOWED` — controls write gate.
- `GITHUB_MCP_DIAGNOSTICS` — enable/disable noisy exception logging.
- `GITHUB_MCP_RECORD_RECENT_EVENTS` — enable/disable recent tool event recording.
- `MCP_RECENT_TOOL_EVENTS_CAPACITY` — cap for recent tool events buffer.
