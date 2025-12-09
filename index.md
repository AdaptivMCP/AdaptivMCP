# ChatGPT GitHub MCP Server

This repository implements a GitHub MCP (Model Context Protocol) server that lets assistants work on GitHub repositories like a careful, senior engineer.

The server exposes tools for:

- Reading repository structure, files, issues, pull requests, and CI state.
- Editing files via diffs and commits on feature branches.
- Running tests and linters in a persistent workspace.
- Opening and updating pull requests end-to-end.

The `controller_contract` tool is the authoritative description of how controllers and assistants should interact with this server. The documents in `docs/assistant/` and `docs/start_session.md` expand on the contract with concrete prompts and workflows.

## Quick links

- [Controller contract (tool)](#controller-contract-tool)
- [Assistant controller prompt](docs/assistant/CONTROLLER_PROMPT_V1.md)
- [Assistant handoff and behavior](docs/assistant/ASSISTANT_HANDOFF.md)
- [Startup sequence for new sessions](docs/start_session.md)
- [Detailed MCP tools reference](Detailed_Tools.md)

## Controller contract (tool)

Controllers should call the `controller_contract` MCP tool at the start of a session (usually with `compact=true`) and surface its expectations in their system prompts. If written documentation ever disagrees with `controller_contract`, the contract wins and the docs should be updated via a pull request.

At a high level, the contract describes:

- How assistants discover tools (`list_all_actions`, `describe_tool`, `validate_tool_args`).
- How write gating works and when write tools may be used.
- The expected branch, diff, test, and pull-request workflow.
- How to avoid large payloads by using file slices, diffs, and focused workspace commands.

## Documentation map

- `README.md`: High-level project overview and setup notes.
- `index.md` (this file): Entry point for controllers and assistant authors.
- `docs/start_session.md`: Recommended startup sequence and controller-facing guidance.
- `docs/assistant/ASSISTANT_HANDOFF.md`: Detailed expectations for assistants using this server.
- `docs/assistant/CONTROLLER_PROMPT_V1.md`: Copy-pasteable controller prompt wired to `controller_contract`.
- `Detailed_Tools.md`: Human-readable reference for every MCP tool exposed by this server.

For day-to-day use, controllers should keep the branch–diff–test–PR flow visible in their prompts and rely on `controller_contract` plus these docs to keep assistants aligned with the live server behavior.
