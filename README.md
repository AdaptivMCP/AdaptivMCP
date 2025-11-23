# chatgpt-mcp-github
Custom GitHub connector for ChatGPT MCP.

## Configuration

- `GITHUB_PAT` / `GITHUB_TOKEN`: GitHub access token (required for private repo access).
- `GITHUB_MCP_AUTO_APPROVE`: Set to `1` to auto-approve GitHub tools for the session (useful for trusted deployments like Render.com where you want commits to work without an extra authorization call).

