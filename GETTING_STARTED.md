# Getting started (Adaptiv Controller – GitHub MCP Server)

This repository is the engine behind **Joey’s GitHub** (an Adaptiv Controller): a self-hosted MCP server that exposes GitHub + a persistent workspace as tools for assistants.

If you are new:

1. Deploy the server (Render or Docker).
2. Connect it to ChatGPT as an MCP integration.
3. In your controller prompt, follow the documented workflows.

## 1) Deploy

### Option A: Render (recommended)

- Create a Render Web Service from this repo.
- Build command:
  - `pip install -r dev-requirements.txt`
- Start command:
  - `uvicorn main:app --host 0.0.0.0 --port 8000`

Required environment variables:

- `GITHUB_PAT` (or `GITHUB_TOKEN`): GitHub token.
- `GITHUB_MCP_CONTROLLER_REPO`: defaults to this repo.
- `GITHUB_MCP_CONTROLLER_BRANCH`: defaults to `main`.

Optional but strongly recommended (Render observability + CLI):

- `RENDER_API_KEY`
- `RENDER_SERVICE_ID`
- `RENDER_OWNER_ID`

Tool / output safety:

- `TOOL_STDOUT_MAX_CHARS`
- `TOOL_STDERR_MAX_CHARS`
- `TOOL_STDIO_COMBINED_MAX_CHARS`

See `.env.example` for the full list and the expected shape of each variable.

### Option B: Docker / Docker Compose

See:

- `docs/human/SELF_HOSTING_DOCKER.md`
- `docs/human/SELF_HOSTED_SETUP.md`

## 2) Verify the service

- Health check:
  - `GET /healthz`

From ChatGPT (once the MCP integration is connected), run:

- `get_server_config`
- `validate_environment`
- `list_all_actions` (optionally `include_parameters=true`)

## 3) Connect in ChatGPT

- Add a new MCP integration using your service URL.
- Create a custom assistant (controller) that uses the integration.

Recommended baseline prompt/docs:

- `docs/assistant/CONTROLLER_PROMPT_V1.md`
- `docs/assistant/start_session.md`
- `docs/human/WORKFLOWS.md`

## 4) Recommended first session flow

1. Confirm the server is healthy and learn defaults:
   - `get_server_config`, `get_repo_defaults`
2. Discover the live tool surface:
   - `list_all_actions` (then `describe_tool` for anything unfamiliar)
3. Validate your “developer loop” works:
   - `ensure_workspace_clone` (controller repo)
   - `terminal_command` (e.g., `python cli.py --version`)
   - `run_tests` or `run_quality_suite`
4. If you are using Render:
   - `list_render_logs`
   - `get_render_metrics`

## Where to go next

- Workflows and expectations: `docs/human/WORKFLOWS.md`
- Architecture and safety model: `docs/human/ARCHITECTURE_AND_SAFETY.md`
- Operational guidance (redeploys, CI, logs): `docs/human/OPERATIONS.md`
- Tool reference + naming: `Detailed_Tools.md`
