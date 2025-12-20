# SELF_HOSTED_SETUP: Deploying the Adaptiv Controller GitHub MCP Server

This guide explains how to deploy this repository as a self-hosted GitHub MCP server and connect it to ChatGPT as a custom controller (for example, `Joey's GitHub`).

The intended audience is:

- People deploying the server for themselves (for example on Render).
- Individuals and small groups who want to run their own backend.

The Adaptiv Controller product is the controller configuration and workflows inside ChatGPT. This repository is the GitHub MCP server that those controllers talk to. You host it yourself and supply your own GitHub credentials; the controller never sees your token directly.

---

## 1. Prerequisites

Before you deploy, you will need:

1. A GitHub account with access to the repositories you want the controller to manage.
2. A GitHub personal access token (classic or fine-grained) with appropriate scopes.
3. A hosting account (Render.com is the primary example here, but any platform that can run a long-lived Python web service will work).
4. A ChatGPT account that supports custom MCP controllers.

### 1.1 GitHub token scopes

The required scopes depend on what you want the controller to do. At minimum, for typical repo workflows:

- `repo` (or fine-grained equivalent) for:
  - Reading and writing code.
  - Creating branches and commits.
  - Opening and updating pull requests.
  - Creating and updating issues.
- Optional additional scopes, depending on usage:
  - `read:org` if you need to inspect private org repositories and metadata.
  - `workflow` if you plan to interact with GitHub Actions workflow runs via the provided tools.

For security, prefer a fine-grained token scoped to specific repositories where possible.

### 1.2 Hosting assumptions

The examples below assume Render.com:

- You connect your GitHub account to Render.
- You create a new Web Service pointing at this repository or your fork of it.
- Render handles build and deploy.

Other platforms (Fly.io, Railway, ECS, Kubernetes, bare metal, etc.) are also fine as long as they can:

- Install Python dependencies.
- Run a long-lived process that exposes an HTTP server.

---

## 2. Get the code (repo or bundle)

You can either:

- Use this repository directly (`Proofgate-Revocations/chatgpt-mcp-github`).
- Fork it into your own GitHub account (recommended if you plan to customize tools or workflows).
- Or receive a versioned source bundle (for example `adaptiv-controller-v0.1.0.tar.gz`) from the author.

If you fork the repo, your controller repo name will be something like `your-username/chatgpt-mcp-github`.

If you received a bundle, unpack it (for example into `adaptiv-controller-v0.1.0/`) and treat that directory as the repository root when configuring your hosting provider.

---

## 3. Environment configuration

The MCP server is configured primarily via environment variables. Common settings include:

- `GITHUB_TOKEN` / `GITHUB_PAT`
  - Your GitHub personal access token. `GITHUB_PAT` takes precedence when both are set.

- `GITHUB_MCP_CONTROLLER_REPO`
  - The full name of the controller repository.
  - Defaults to `Proofgate-Revocations/chatgpt-mcp-github`.
  - If you forked the repo, set this to your fork, for example `your-username/chatgpt-mcp-github`.

- `GITHUB_MCP_CONTROLLER_BRANCH`
  - The default branch that the server should consider canonical for its own repo.
  - Defaults to `main` when unset.
  - You can temporarily point this at a feature branch during long-running refactors (for example `feature/refactor-xyz`), then switch it back to `main` after the refactor is merged.
  - This value is used by the `_effective_ref_for_repo` helper to avoid accidental writes to the wrong branch.

- Write gating defaults to manual approval. Controllers must call
  `authorize_write_actions(approved=True)` before any write-tagged tools will
  run. Use this to keep destructive operations behind an explicit confirmation
  step.

Additional optional variables may exist for HTTP timeouts, retry settings, and logging.

### Output truncation and payload sizing

Long `terminal_command` / `run_tests` outputs can cause the ChatGPT client to drop or
replace a conversation thread. Deployments can clamp stdout/stderr with:

- `TOOL_STDOUT_MAX_CHARS` and `TOOL_STDERR_MAX_CHARS`
  - Hard caps for each stream. Defaults are `12000` and `6000` characters.
  - Set lower values if Render or your MCP client struggles with large payloads.
- `TOOL_STDIO_COMBINED_MAX_CHARS`
  - Upper bound for stdout + stderr together (default `18000`).
  - Useful on Render to keep responses safely under provider and client constraints
    without losing truncation signals (both streams include `*_truncated` flags).

For a canonical, copy-pasteable list of supported variables, see the
`.env.example` file in the repository root. It contains commented examples for
all commonly used settings, along with brief descriptions and recommended
defaults. When deploying on providers like Render, you can open `.env.example`
side-by-side with your service's environment configuration and copy variable
names directly, supplying values appropriate for your deployment.

Check the repository README and configuration sections for any new variables added over time.

> Meta tools for verification and troubleshooting:
> - Use `get_server_config` to confirm the effective configuration (write gating, timeouts, constraints).
> - Use `list_all_actions` to see all registered tools and their write/read status.
> - Use `ping_extensions` to verify that `extra_tools.py` and any other extensions loaded correctly.

---

## 4. Deploying on Render (example)

The exact steps may change as Render evolves, but the high-level flow is:

1. **Connect GitHub to Render**
   - Log in to Render.com.
   - Connect your GitHub account if you have not already.

2. **Create a new Web Service**
   - Select your repo (this repo or your fork).
   - Choose a name (for example `adaptiv-controller-github-mcp`).

3. **Configure build and start commands**

Typical configuration might look like:

- Build command:
  - `pip install -r dev-requirements.txt`

- Start command:
  - `uvicorn main:app --host 0.0.0.0 --port 8000`

Adjust these commands if the repo uses a different entrypoint or packaging model. The key requirement is that the process starts a FastMCP-compatible HTTP server.

4. **Set environment variables**

4. **Edge caching (Render)**
   - This server uses long-lived SSE connections (`/sse`) and POST callbacks (`/messages`).
   - These endpoints must **never** be cached. The server already emits `Cache-Control: no-store`, but
     enabling aggressive edge caching can still break ChatGPT connectivity if misconfigured.
   - Recommended Render setting: enable edge caching for **static assets only** (or disable edge caching).
   - If you change edge caching settings, also **purge the edge cache** and refresh the connector in ChatGPT.

   - `GITHUB_TOKEN`: your token.
   - `GITHUB_MCP_CONTROLLER_REPO`: your controller repo full name (if different).
   - `GITHUB_MCP_CONTROLLER_BRANCH`: the default branch for the controller repo (`main` or a refactor branch).
   - Output caps to protect the ChatGPT client from oversized responses:
     - `TOOL_STDOUT_MAX_CHARS`, `TOOL_STDERR_MAX_CHARS`, and `TOOL_STDIO_COMBINED_MAX_CHARS`.
   - Any additional configuration keys required by this repo's README.

5. **Deploy**
   - Trigger the initial deploy.
   - Wait for Render to build and start your service.

6. **Verify health**
   - Once deployed, obtain the public URL for your service.
   - You will use this URL when configuring the custom controller in ChatGPT.

---

## 5. Sanity-checking the MCP server

Once the service is running, it is important to verify that it is exposing the expected tools and configuration. The easiest way to do this is from ChatGPT after you connect the MCP controller.

Within ChatGPT, after connecting the MCP server (see the next section), you can call:

- `get_server_config` to see the server's advertised capabilities.
- `list_all_actions` to enumerate all tools and confirm they are registered correctly.
- `ping_extensions` to check that `extra_tools.py` was imported and wired into the registry.

These tools help verify that:

- Your token is valid and the server can reach GitHub.
- The correct branch defaults are in effect for the controller repo.
- `extra_tools` are available.

If any of these tools fail, check your Render logs and environment variable configuration.

In addition, the HTTP server exposes a built-in JSON health endpoint at `/healthz`:

- It returns a small payload containing status, uptime (in seconds since process start), whether a GitHub token is present, the configured controller repo/default branch, and a compact metrics snapshot.
- It is safe to use for uptime probes and dashboards; the body stays small and numeric and never includes secrets or full request payloads.
- On Render, you can point the health check at `GET /healthz` instead of implementing a separate endpoint.

---

## 6. Connecting the MCP server to ChatGPT

Once your MCP server is live, you can connect it to ChatGPT as a custom MCP integration. The exact UI may change, but the high-level steps are:

1. **Add a new MCP integration**
   - In ChatGPT's settings or in the custom GPT editor, add a new MCP server.
   - Provide the base URL of your Render deployment.

2. **Confirm connectivity**
   - Use a simple test assistant to call `get_server_config`.
   - Confirm that you can see the expected tools and metadata.

3. **Create a controller (Adaptiv Controller instance)**
   - Create a new custom GPT or assistant in ChatGPT.
   - Attach the MCP integration you just configured.
   - Apply the Adaptiv Controller system prompt and instructions that describe how to use the tools (these are part of the product you purchased or designed).
   - Give the controller any display name you like (for example, `Joey's GitHub`).

From this point on, the controller can call the tools exposed by your self-hosted MCP server to read and write GitHub data according to the safety model documented in `docs/human/ARCHITECTURE_AND_SAFETY.md`.
---

## 7. Safety model recap (operator view)

When you deploy this server, keep the following in mind:

- **Write gating**
  - Destructive tools are tagged as write actions and are gated by a global `WRITE_ALLOWED` flag.
  - You (or your controller) must call `authorize_write_actions(approved=True)` before any write tools will run.

- **Branch defaults**
  - The controller repo uses `_effective_ref_for_repo` to avoid accidental writes to `main`.
  - For other repos, missing refs default to `main`; adjust your controller prompt to encourage safe branch-based workflows.

- **Verification**
  - Write flows use read-after-write verification and compare SHAs.
  - Patch-based edits fail if the underlying file does not match the expected context.

- **Workspace commands**
  - `terminal_command` and `run_tests` operate in a persistent clone of your repo so installs and edits survive between calls.
  - Output is truncated according to configured caps, with explicit flags when truncation occurs.

For more detail, see `docs/human/ARCHITECTURE_AND_SAFETY.md`.

---

## 8. Troubleshooting

Common issues and fixes:

1. **MCP server fails to start**
   - Check Render logs for Python import errors or syntax errors.
   - Ensure dependencies were installed (`pip install -r dev-requirements.txt`).

2. **GitHub API calls fail with 401 or 403**
   - Verify `GITHUB_TOKEN` is set and has the required scopes.
   - Confirm the token is not expired or revoked.
   - Check that the token has access to the repositories you are targeting.

3. **Tools reference the wrong branch**
   - Confirm `GITHUB_MCP_CONTROLLER_BRANCH` is set correctly for the controller repo.
   - Check that your controller prompt is passing the branch you expect when calling tools on user repos.

4. **Large outputs are truncated unexpectedly**
   - Check or adjust `TOOL_STDOUT_MAX_CHARS` and `TOOL_STDERR_MAX_CHARS`.
   - Remember that truncation is a safety feature; very large outputs can be difficult for the assistant to handle.

5. **Extra tools are missing**
   - Ensure `extra_tools.py` is present and that `register_extra_tools` is imported and called from `main.py`.
   - Use `ping_extensions` to confirm that extra tools were registered.

If you get stuck, open a GitHub issue in your controller repo, describe your environment (Render config, env vars, logs), and use the issue tools from the controller itself to track debugging steps.

---

## 9. Next steps

For installation, upgrades, and rollbacks specifically:

- Use this document (`SELF_HOSTED_SETUP.md`) for initial deployment and high-level configuration.
- Use `docs/human/UPGRADE_NOTES.md` for guidance on moving between versions (staging vs production, tagging, and rollback strategies).

In short:

- Treat staging and production as separate services.
- Pin production to a known-good branch, tag, or commit.
- Run smoke tests and workspace tests after every upgrade, and roll back quickly if something looks wrong.

Once your self-hosted MCP server is running and wired into ChatGPT, you can:

- Iterate on your controller prompt and workflows (see `docs/human/WORKFLOWS.md`).
- Extend the server with additional tools via `extra_tools.py`.
- Tighten or relax policies by adjusting your controller instructions and when you enable `WRITE_ALLOWED`.

Because this server is self-hosted, you retain full control over:

- Which repositories and branches the controller can access.
- When destructive operations are allowed.
- How logs, metrics, and observability are configured in your hosting environment.



## 9.5 Optional: Render observability + web browser tools

If you deploy on Render and want assistants to be able to see deploy context without leaving the chat:

- Set `RENDER_API_KEY` and (recommended) `RENDER_SERVICE_ID` and `RENDER_OWNER_ID`.
- The server exposes:
  - `list_render_logs` (read)
  - `get_render_metrics` (read)

If you want assistants to be able to look up external documentation and validate facts:

- The server exposes:
  - `web_search`
  - `web_fetch`

These tools are enabled server-side and are available to any assistant that connects to the MCP server.


## 10. Versioning and CLI checks

For the 1.0 release of this server, version information is wired in three places:

- `pyproject.toml` — `project.version = "1.0.0"`.
- `CHANGELOG.md` — documents each released version (starting with `1.0.0`).
- `cli.py` — a small CLI that reads the version from `pyproject.toml`.

To confirm the version in a given environment (local dev, Render shell, or the controller workspace):

1. Open a shell in the deployment (or use the `terminal_command` tool against this repo).
2. From the repository root, run:

   ```bash
   python cli.py --version
   ```

3. You should see `1.0.0` for the 1.0 release.

In future releases:

- Update `pyproject.toml` and `CHANGELOG.md` together.
- Tag the release in Git (for example `v1.0.1`, `v1.1.0`).
- Follow `docs/human/UPGRADE_NOTES.md` for staging → production rollout.

Treat these version indicators as a single source of truth for which Adaptiv Controller build is deployed.
