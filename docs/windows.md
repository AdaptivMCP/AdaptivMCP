# Windows 11 quick start

AdaptivMCP can run locally on Windows 11 without WSL or Docker.

## Prerequisites

Install:

- Python **3.12.x** (Python 3.13 is not the supported runtime version)
- Git for Windows

The launcher checks both before changing anything.

## One-click launch

1. Clone the repository:
   ```powershell
   git clone https://github.com/AdaptivMCP/AdaptivMCP.git
   cd AdaptivMCP
   ```
2. Double-click `scripts\launch-windows.cmd`.
3. The first run creates `.venv`, installs dependencies, and asks for your GitHub token.
4. The launcher creates a local `.env` containing a randomly generated MCP bearer token.
5. The server starts on `http://127.0.0.1:8000`.

The MCP Streamable HTTP endpoint is:

`http://127.0.0.1:8000/mcp`

Health check:

`http://127.0.0.1:8000/healthz`

## PowerShell usage

From the repository root:

```powershell
.\scripts\windows-start.ps1
```

Choose another port:

```powershell
.\scripts\windows-start.ps1 -Port 8080
```

Install/setup only:

```powershell
.\scripts\windows-start.ps1 -InstallOnly
```

## Configuration

The first run creates `.env`. It is ignored by Git and must never be committed.

The launcher configures:

- `GITHUB_TOKEN` — GitHub authentication.
- `ADAPTIV_MCP_AUTH_TOKEN` — local bearer authentication, generated automatically.
- `ADAPTIV_MCP_ALLOWED_HOSTS` / `ADAPTIV_MCP_ALLOWED_ORIGINS` — restricted to localhost.
- `MCP_WORKSPACE_BASE_DIR` — Windows-friendly persistent workspace directory under LocalAppData.

For Render tools, add `RENDER_API_KEY` to `.env` after setup.

## Updating

Run the launcher again after pulling changes. It reuses the existing virtual environment and refreshes the runtime dependencies.

If the environment becomes corrupted, delete `.venv` and run the launcher again.

## Troubleshooting

### Python is not found

Install Python 3.12.x and ensure the Python launcher (`py.exe`) is available.

### Git is not found

Install Git for Windows and reopen PowerShell/Command Prompt so PATH changes are picked up.

### Port 8000 is already in use

Start on another port:

```powershell
.\scripts\windows-start.ps1 -Port 8080
```

### ChatGPT/MCP client cannot connect

Use the Streamable HTTP URL ending in `/mcp`. The local server binds to loopback only, so it is intentionally not directly reachable from the public internet. For a remote ChatGPT connector, use a secure tunnel or hosted deployment rather than exposing the development server directly.
