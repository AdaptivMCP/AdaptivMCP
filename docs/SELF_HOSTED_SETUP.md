# SELF_HOSTED_SETUP: Deploying the Adaptiv Controller GitHub MCP Server

This guide explains how to deploy this repository as a self-hosted GitHub MCP server and connect it to ChatGPT as a custom controller (for example, `Joey's GitHub`).

The intended audience is:

- Engineers and operators deploying the server (for example on Render).
- Buyers of the Adaptiv Controller product who need to run their own backend.

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

## 2. Fork or clone the repository

You can either:

- Use this repository directly (`Proofgate-Revocations/chatgpt-mcp-github`).
- Or fork it into your own GitHub account (recommended if you plan to customize tools or workflows).

If you fork the repo, your controller repo name will be something like `your-username/chatgpt-mcp-github`.

You will point your hosting provider at this repo (or fork) when you configure the service.

---

## 3. Environment configuration

The MCP server is configured primarily via environment variables. Common settings include:

- `GITHUB_TOKEN`
  - Your GitHub personal access token. Required.

- `GITHUB_MCP_CONTROLLER_REPO`
  - The full name of the controller repository.
  - Defaults to `Proofgate-Revocations/chatgpt-mcp-github`.
  - If you forked the repo, set this to your fork, for example `your-username/chatgpt-mcp-github`.

- `GITHUB_MCP_CONTROLLER_BRANCH`
  - The default branch that the server should consider canonical for its own repo.
  - During refactor phases this may be a feature branch (for example `ally-mcp-github-refactor-fresh`).
  - Once the refactor is merged, this should typically be set to `main`.
  - This value is used by the `_effective_ref_for_repo` helper to avoid accidental writes to the wrong branch.


- `GITHUB_MCP_AUTO_APPROVE`
  - Controls the default write behavior for tools tagged as write actions.
  - When unset or set to a falsey value, the server starts in **manual approval**
    mode and `WRITE_ALLOWED` defaults to `False`. In this mode, controllers
    must call the `authorize_write_actions(approved=True)` tool before any
    write-tagged tools will run.
  - When set to a truthy value (for example `1`, `true`, `yes`, or `on`), the
    server starts in **auto-approve** mode and `WRITE_ALLOWED` defaults to
    `True`. Write tools are immediately allowed, but controllers can still call
    `authorize_write_actions(approved=False)` to temporarily disable writes for
    a session.
  - For production deployments where you want an extra confirmation step for
    destructive operations, leaving this variable unset (manual approval) is
    recommended.

Additional optional variables may exist for:

- HTTP timeouts and retry settings.

For a canonical, copy-pasteable list of supported variables, see the
`.env.example` file in the repository root. It contains commented examples for
all commonly used settings, along with brief descriptions and recommended
defaults. When deploying on providers like Render, you can open `.env.example`
side-by-side with your service's environment configuration and copy variable
names directly, supplying values appropriate for your deployment.

Check the repository README and configuration sections for any new variables added over time.

Check the repository README and configuration sections for any new variables added over time.

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
  - `pip install -r requirements.txt`

- Start command:
  - `uvicorn main:app --host 0.0.0.0 --port 8000`

Adjust these commands if the repo uses a different entrypoint or packaging model. The key requirement is that the process starts a FastMCP-compatible HTTP server.

4. **Set environment variables**
   - `GITHUB_TOKEN`: your token.
   - `GITHUB_MCP_CONTROLLER_REPO`: your controller repo full name (if different).
   - `GITHUB_MCP_CONTROLLER_BRANCH`: the default branch for the controller repo (`main` or a refactor branch).
   - Any additional configuration keys required by this repo's README.

5. **Deploy**
   - Trigger the initial deploy.
   - Wait for Render to build and start your service.

6. **Verify health**
   - Once deployed, obtain the public URL for your service.
   - You will use this URL when configuring the custom controller in ChatGPT.

---

## 5. Sanity-checking the MCP server

Once the service is running, it is important to verify that it is exposing the expected tools and configuration. The easiest way to do this is from ChatGPT after you connect the MCP controller, but you can also implement a basic health endpoint if needed.

Within ChatGPT, after connecting the MCP server (see the next section), you can call:

- `get_server_config` to see the server's advertised capabilities.
- `list_all_actions` to enumerate all tools and confirm they are registered correctly.
- `ping_extensions` to check that `extra_tools.py` was imported and wired into the registry.

These tools help verify that:

- Your token is valid and the server can reach GitHub.
- The correct branch defaults are in effect for the controller repo.
- `extra_tools` are available.

If any of these tools fail, check your Render logs and environment variable configuration.

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

From this point on, the controller can call the tools exposed by your self-hosted MCP server to read and write GitHub data according to the safety model documented in `docs/ARCHITECTURE_AND_SAFETY.md`.

---

## 7. Safety model recap (operator view)

When you deploy this server, keep the following in mind:

- **Write gating**
  - Destructive tools are tagged as write actions and are gated by a global `WRITE_ALLOWED` flag.
  - You (or your controller) must call `authorize_write_actions(approved=True)` before any write tools will run.

- **Branch defaults**
  - The controller repo uses `_effective_ref_for_repo` to avoid accidental writes to `main`.
  - For other repos, missing refs default to `main`, but your controller prompt should still encourage branch-first workflows.

- **Verification**
  - Write flows use read-after-write verification and compare SHAs.
  - Patch-based edits fail if the underlying file does not match the expected context.

- **Workspace commands**
  - `run_command` and `run_tests` operate in a temporary clone of your repo.
  - Output is truncated according to configured limits, with explicit flags when truncation occurs.

For more detail, see `docs/ARCHITECTURE_AND_SAFETY.md`.

---

## 8. Troubleshooting

Common issues and fixes:

1. **MCP server fails to start**
   - Check Render logs for Python import errors or syntax errors.
   - Ensure dependencies were installed (`pip install -r requirements.txt`).

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

Once your self-hosted MCP server is running and wired into ChatGPT, you can:

- Iterate on your controller prompt and workflows (see `docs/WORKFLOWS.md`).
- Extend the server with additional tools via `extra_tools.py`.
- Tighten or relax policies by adjusting your controller instructions and when you enable `WRITE_ALLOWED`.

Because this server is self-hosted, you retain full control over:

- Which repositories and branches the controller can access.
- When destructive operations are allowed.
- How logs, metrics, and observability are configured in your hosting environment.

This is what makes the Adaptiv Controller pattern powerful: you keep ownership of your infrastructure and credentials, while the controller logic and this MCP server provide safe, repeatable GitHub workflows for your assistants.