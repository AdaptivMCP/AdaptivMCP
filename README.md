# Adaptiv MCP (GitHub + Render)

Adaptiv MCP is a self-hosted, connector-oriented **Model Context Protocol (MCP)** server that exposes **GitHub** and **Render** automation as MCP tools, plus a small HTTP registry/UI surface for discovery and debugging.

It’s designed to work cleanly with **ChatGPT / OpenAI MCP connectors** (including common preflight/probe behavior).

## What you get

- You can use this App to use ChatGPT to find/update bugs, issues, tests, PR etc.
- You can use this App to create brand new Apps etc. without any knowledge of coding to begin with.
- You can use this App as a Professional Developer who uses ChatGPT in everyday workflows.
- You can FULLY customize this APP by modifying the code and adding new MCP tools for new endpoints for different uses other than just Github/Render/Coding etc.

### Tooling

- **GitHub automation**
  - repos, branches, files
  - issues + comments
  - pull requests (open/merge/close/comment)
  - GitHub Actions workflows (list runs, trigger dispatch, fetch logs)
- **Render automation**
  - list services / deploys
  - trigger/cancel/rollback deploys
  - restart services
  - fetch logs
- **Workspace / repo mirror** (server-side git working copy)
  - apply file edits safely
  - run commands/tests in a real checkout
  - commit/push and open PRs via a “mirror-first” workflow

### Connector-friendly server behaviors

- **Two MCP transports**
  - **Streamable HTTP (preferred):** `POST /mcp`
  - **Legacy SSE transport:** `GET /sse` + `POST /messages`
- **Preflight-safe endpoints** for `OPTIONS` / `HEAD` / `GET` probes
- **Base-path safe links** via `GET /ui.json` when deployed behind a reverse proxy prefix

## Endpoints

MCP transports:

- **Streamable HTTP:** `POST /mcp`
- **SSE:** `GET /sse` and `POST /messages`

HTTP registry/diagnostics:

- `GET /healthz` – runtime health
- `GET /tools` – tool discovery used by connectors
- `POST /tools/<tool_name>` – invoke a tool over HTTP
- `GET /resources` – resource discovery
- `GET /ui` – lightweight UI (links + diagnostics)
- `GET /ui/tools` – tool catalog UI
- `GET /ui.json` – machine-readable service metadata (base-path aware)

## Deploying on Render.com

1) Make a Render.com account and start a Web Service.

<img width="1896" height="711" alt="{FE34540B-8AE0-41A0-97B3-D91FABA184B9}" src="https://github.com/user-attachments/assets/623f34a6-8aa7-4799-8fb8-f59c223db44f" />

2) Use these Start/Build Commands

<img width="1415" height="389" alt="{B62E07CF-D6AB-413F-8181-D5484E7FC75C}" src="https://github.com/user-attachments/assets/570d7dae-b4f3-4e8e-86eb-ddbd0805a71c" />

3) Setup Evironment Variables
Example:
<img width="1678" height="481" alt="{E012574C-E7BA-4AC5-BFA6-2BD653EBACEC}" src="https://github.com/user-attachments/assets/ece377be-f91f-410b-8db7-9e7d7cae3d43" />

(ADAPTIV_MCP_CONTROLLER_REPO set to your mainly worked on Repo. can still see all repos scoped in the Github PAT.)

<img width="1569" height="223" alt="{B25AF1F7-6B36-4E12-BAA0-22BB501F67B9}" src="https://github.com/user-attachments/assets/4e8aaf36-2783-470d-afae-f4a3d01c695b" />

<img width="1567" height="348" alt="{63A3218A-C64F-4551-B8E2-9E23ADEFFABE}" src="https://github.com/user-attachments/assets/0906c70d-f50a-4d81-8471-72a2d7a00916" />

4) Open ChatGPT and go to Settings>Apps>Create App and set it up with the URL you recieved with /sse at the end.

<img width="447" height="704" alt="{57BA9AF6-612A-4423-82DB-75DBEDBBC3E5}" src="https://github.com/user-attachments/assets/1d9f46b4-c2bb-4a11-8155-42cb389af20a" />

5) Connect your chat message in ChatGPT with your custom made App.

<img width="784" height="114" alt="{6DD876A1-130F-4B17-BBFD-9035C74B3F31}" src="https://github.com/user-attachments/assets/451b85f2-ef83-4a14-bed2-ffd7ea290e38" />

6) You can now Clone any Repo and use with the provided Github OAUTH scope which you provide and enter into the environment variables on Render.com

Examples:

- **Tell ChatGPT Assistant to use validate_environment to make sure everything is setup correctly.**

<img width="891" height="649" alt="{95D17859-C0CF-4BD9-AA77-3C552DC4C43D}" src="https://github.com/user-attachments/assets/ac7bf568-b3d0-4de9-8be0-77c340430206" />

<img width="532" height="450" alt="{159AC69A-6757-4172-9468-00BC07E84824}" src="https://github.com/user-attachments/assets/f86d3031-d387-40b2-95f8-efcadd1b4ae6" />

<img width="907" height="373" alt="{49256559-D385-4015-8B49-88551D709270}" src="https://github.com/user-attachments/assets/5cbc3d7e-0df2-4c08-bd3a-a5db535154e1" />


### GitHub auth

Set **at least one** token variable:

- `GITHUB_TOKEN` (common)
- `GITHUB_PAT`, `GH_TOKEN`, `GITHUB_OAUTH_TOKEN` (alternates)

Optional:

- `GITHUB_API_BASE` – override for GitHub Enterprise / custom API base (defaults to `https://api.github.com`)

### Render auth

Set one token variable:

- `RENDER_API_KEY` (common)
- `RENDER_API_TOKEN`, `RENDER_TOKEN` (alternates)

### Workspace / repo mirror

Workspace tools operate on a **persistent** server-side repo mirror (git working copy). Useful settings:

- `MCP_WORKSPACE_BASE_DIR` – where mirrors are stored (defaults under your cache directory)

## Deployment notes

### Render

This repo includes Render-friendly scripts:

- `scripts/render-build.sh` – installs dependencies with a hash marker to speed subsequent deploys
- `scripts/render-start.sh` – validates a vendored `rg` binary, normalizes log level for uvicorn, and starts the server

The start script expects a working `rg` on `$PATH` and will prefer the vendored binaries under `vendor/rg/...`.
