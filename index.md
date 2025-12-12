# Adaptiv Controller – GitHub MCP Server

This repository implements a GitHub MCP (Model Context Protocol) server that lets assistants work on GitHub repositories like a careful, senior engineer, using branches, tests, and pull requests as their main workflow.

The server exposes tools for:

- Reading repository structure, files, issues, pull requests, and CI state.
- Editing files via diffs and commits on feature branches.
- Running tests and linters in a persistent workspace.
- Opening and updating pull requests end-to-end.

## Quick links

- [Assistant controller prompt](docs/assistant/CONTROLLER_PROMPT_V1.md)
- [Assistant handoff and behavior](docs/assistant/ASSISTANT_HANDOFF.md)
- [Startup sequence for new sessions](docs/start_session.md)
- [Detailed MCP tools reference](Detailed_Tools.md)

## Documentation map

- `README.md`: High-level project overview and setup notes.
- `index.md` (this file): Entry point for controller authors and assistant prompt designers.
- `docs/start_session.md`: Recommended startup sequence and controller-facing guidance.
- `docs/assistant/ASSISTANT_HANDOFF.md`: Detailed expectations for assistants using this server.
- `docs/assistant/CONTROLLER_PROMPT_V1.md`: Copy-pasteable controller prompt for assistants using this server.
- `Detailed_Tools.md`: Human-readable reference for every MCP tool exposed by this server.

For day-to-day use, controllers should keep the branch–diff–test–PR flow visible in their prompts and rely on these docs to keep assistants aligned with the live server behavior.