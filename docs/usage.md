# Usage

This repository provides a lightweight MCP server exposing GitHub and workspace tools.

## Notes

Response-size truncation environment variables and related code paths were removed.
If you encounter references to max-character response limits elsewhere, treat them as obsolete.

## Workspace clone location

Workspace tools (like `terminal_command` and file operations) run against a
persistent repo mirror on the server. The clone lives on the host filesystem,
not inside a container, so paths should be treated as server-side paths rather
than local machine paths.

By default, the repo mirror root lives at:

```
~/.cache/mcp-github-workspaces
```

Set `MCP_WORKSPACE_BASE_DIR` to override the base directory if you need the
clones stored elsewhere.
