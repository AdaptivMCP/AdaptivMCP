# Self-hosting with Docker and Docker Compose (Joey's GitHub)

This document explains how to run the Adaptiv Controller GitHub MCP server using Docker and Docker Compose. It is written for individual developers who want to run the backend on their own machine or infrastructure and use a controller inside ChatGPT (for example, a controller named "Joey's GitHub") to drive it.

At a high level:

- The MCP server runs in your environment (Docker Desktop, a VM, or any Docker-capable host).
- The controller in ChatGPT connects to this MCP server.
- The controller does most of its work via `run_command` in a persistent workspace, including installing any dependencies the repo needs, creating branches, committing changes, and opening pull requests.

---

## 1. Prerequisites

You will need:

- Docker Desktop or Docker Engine installed and running.
- Git installed.
- A GitHub personal access token (PAT) or GitHub App token with access to the repositories you want the controller to operate on.

> The controller can read/write any repo your token can access. Use a fine-grained PAT scoped to specific repos if you want to limit scope.

---

## 2. Clone the repository locally

Clone this repo (or your fork) and switch into it:

```bash
git clone https://github.com/Proofgate-Revocations/chatgpt-mcp-github.git
cd chatgpt-mcp-github
```

Make sure you are on the `main` branch and up to date:

```bash
git checkout main
git pull
```

---

## 3. Configure environment variables for Docker

This repository includes `.env.example` at the root. Copy it to `.env` and edit values as needed:

```bash
cp .env.example .env
```

Open `.env` in your editor and set at least:

```dotenv
# REQUIRED: your GitHub token (PAT or GitHub App token)
GITHUB_PAT=ghp_your_token_here
# Controller repo (defaults are fine if you use this repo)
GITHUB_MCP_CONTROLLER_REPO=Proofgate-Revocations/chatgpt-mcp-github
GITHUB_MCP_CONTROLLER_CONTRACT_VERSION=2025-03-16
GITHUB_MCP_CONTROLLER_BRANCH=main

# Write gate behaviour
# false  = controllers must explicitly authorize writes
# true   = write tools are allowed by default
GITHUB_MCP_AUTO_APPROVE=false

# Workspace base directory inside the container.
# This should match the volume mount in docker-compose.yml.
MCP_WORKSPACE_BASE_DIR=/workspace

# HTTP server port inside the container
PORT=8000
```

All other variables in `.env.example` have sensible defaults and can be tuned later (HTTP timeouts, concurrency limits, Git identity, truncation, logging, and sandbox configuration).

Because `docker-compose.yml` wires every tunable variable through from `.env`, you can use `.env.example` as a full reference for all supported knobs.

---

## 4. Run the server with Docker Compose

From the repo root, start the container:

```bash
docker compose up --build
```

This will:

- Build the image using the provided `Dockerfile`.
- Start the `adaptiv-controller-github` container.
- Expose the MCP HTTP server on `http://localhost:8000`.
- Mount `./workspace` on your host as `/workspace` inside the container so `run_command` and `run_tests` can use a persistent workspace.

To stop the container:

```bash
docker compose down
```

To run detached in the background:

```bash
docker compose up --build -d
```

---

## 5. Health checks and verification

Once the container is running, you can verify it from your host machine:

```bash
curl http://localhost:8000/healthz
```

You should see a JSON payload similar to:

```json
{
  "status": "ok",
  "github_token_present": true,
  "controller": {
    "repo": "Proofgate-Revocations/chatgpt-mcp-github",
    "default_branch": "main"
  },
  "metrics": { ... }
}
```

This confirms that:

- The server is running.
- A GitHub token is configured.
- The controller repo and default branch are set correctly.

---

## 6. How Joey's GitHub uses this setup

When you are using a controller like **Joey's GitHub**, the typical workflow against this self-hosted Docker deployment is:

1. **Create a feature branch** from `main` for any change.
2. **Use `run_command` for all repo work** in the workspace clone: file inspection, edits, formatting, tests, and installing any dependencies.
3. **Commit from the workspace** with `commit_workspace`, targeting that feature branch and pushing back to GitHub.
4. **Open a pull request** from the feature branch into `main`.
5. **Review and merge** the PR yourself, then delete the branch.

This matches the same branch-first, PR-based workflow you use when the server is hosted on Render; the only difference is that the MCP HTTP server is running in your own Docker environment instead of a managed platform.

Controllers like **Joey's GitHub** are designed to treat this Docker deployment as just another MCP server. Once it is running and reachable, no prompt or workflow changes are required on the controller side.
