# chatgpt-mcp-github
Custom GitHub connector for ChatGPT MCP.

## Configuration

- `GITHUB_PAT` / `GITHUB_TOKEN`: GitHub access token (required for private repo access).
- `GITHUB_MCP_AUTO_APPROVE`: Set to `1` to auto-approve GitHub tools for the session (useful for trusted deployments like Render.com where you want commits to work without an extra authorization call).

## commit_file_from_url tips

- `content_url` must be reachable from inside the MCP container.
  - Use a real HTTP(S) URL (e.g., a raw GitHub file) when running on Render or any hosted environment.
  - Local paths such as `/mnt/data/foo.txt` only work if that path is actually mounted inside the container (e.g., via a volume). They cannot read files that live only on the host running ChatGPT.
- Example HTTP test payload:
  ```json
  {
    "repository_full_name": "owner/repo",
    "path": "test_commit_from_url_http.txt",
    "content_url": "https://raw.githubusercontent.com/owner/repo/main/README.md",
    "message": "Test commit_file_from_url with public HTTP URL",
    "branch": "main",
    "binary": false,
    "encoding": "utf-8"
  }
  ```
