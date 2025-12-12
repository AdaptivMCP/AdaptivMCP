# Adaptiv Controller – Controller-in-a-box: Getting Started

_Last updated: 2025-12-11_

This guide is written for a **single developer** who has purchased the Adaptiv Controller – GitHub MCP Server as a controller-in-a-box. The goal is to take you from a .zip file to a running MCP server on Render, connected to your own custom controller in ChatGPT.

You do not need to be a DevOps expert. You do need:

- A GitHub account.
- A Render.com account.
- Access to ChatGPT with MCP / custom GPT support.

---

## 1. Unpack the product and create your repo

1. Save the product bundle you received (for example `adaptiv-controller-v1.0.0.zip`).
2. Unzip it on your machine.
3. Create a new **private** repository in your own GitHub account (for example `my-adaptiv-controller`).
4. Initialize the repo and push the unzipped contents:
   - `git init`
---

## 2. Create a GitHub token

You need a GitHub token so the MCP server can talk to the GitHub API on your behalf.

1. Go to GitHub → Settings → Developer settings → Personal access tokens.
2. Create a fine-grained or classic PAT with at least:
   - `repo` scope for the repositories you want the controller to manage.
   - `workflow` scope if you want the controller to inspect GitHub Actions runs and logs.
3. Copy the token; you will paste it into Render as an environment variable.

Do **not** hardcode the token in the repository. It should live only in your hosting environment (Render).

---

## 3. Deploy the MCP server on Render

This repository already includes a `Dockerfile` suitable for Render. The simplest path is:

1. Log into Render and click **New → Web Service**.
2. Point Render at the GitHub repo you created in step 1.
3. Confirm it detects the `Dockerfile`. You should not need to customize the build command.
4. Set the service to expose port `8000` (Render will map it).
5. In the **Environment** section, add variables based on `.env.example` in the repo. At minimum:
   - `GITHUB_PAT` or `GITHUB_TOKEN` – your GitHub token from step 2.
   - `GITHUB_MCP_CONTROLLER_REPO` – set to `<your-username>/<your-repo>` so the server treats your repo as the controller repo.
   - `GITHUB_MCP_AUTO_APPROVE=false` – recommended default; keep writes gated and let your controller explicitly enable them when needed.
   - `PORT=8000` – to match the default in the Dockerfile.

You can also copy `.env.example` to `.env` locally, adjust values, and then copy those values into Render’s environment UI.

Once you have configured the service, let Render build and deploy it. When it is live, visit:

- `https://<your-service>.onrender.com/healthz`

You should see a small JSON blob with status, uptime, and config hints.

---

## 4. Connect ChatGPT to your MCP server

Next, wire this MCP server into ChatGPT. The exact UI may change over time, but the pattern is:

1. In ChatGPT, go to the MCP or integrations section.
2. Add a new MCP server pointing at your Render URL, for example:
   - Base URL: `https://<your-service>.onrender.com`
   - Port: `443` (HTTPS)
3. Save the integration.
4. Start a new chat and select a custom GPT or assistant that can use this MCP server.
5. In the chat, ask it to call:
   - `get_server_config`
   - `validate_environment`

If those tools respond successfully, your controller and MCP server are talking to each other.

---

## 5. Create your personal Adaptiv Controller in ChatGPT

Now you create the controller layer – your personal AI engineer that uses this MCP server.

1. In ChatGPT, create a new custom GPT (or assistant).
2. In its system instructions, paste the current controller prompt from:
   - `docs/assistant/CONTROLLER_PROMPT_V1.md`
3. Give it a name you like (for example `My GitHub Engineer`).
4. Make sure this custom GPT is allowed to use the MCP server you configured in step 4.

Optionally, you can add a preferences file to this repo:

- `docs/adaptiv/preferences.md` – a markdown file describing how you like code organized, how aggressive to be with refactors, how to run tests, and similar.
- Teach your controller (in its prompt) to read and respect this file at startup.

---

## 6. Run a smoke-test workflow

Before trusting the controller on important repositories, run a very small, low-risk test:

1. Create or pick a throwaway repo or branch with simple code or docs.
2. In ChatGPT, ask your controller to:
   - Clone the repo using `ensure_workspace_clone`.
   - Make a tiny, non-destructive change (for example update a README heading).
   - Use the branch/diff/test/PR flow documented in `docs/assistant/ASSISTANT_HAPPY_PATHS.md`.
3. Verify that it:
   - Creates a feature branch (never writes directly to `main`).
   - Applies the change via a patch or simple text update.
   - Runs tests or `run_quality_suite` if applicable.
   - Opens a pull request instead of merging directly.

Once this works, you have confirmed the entire path from ChatGPT → MCP server → GitHub → PR.

---

## 7. Packaging as a controller-in-a-box

If you are the author selling this controller-in-a-box, the recommended packaging for buyers is:

1. Tag a version in Git (for example `v1.0.0`).
2. Create a zip archive of the repository at that tag (for example `adaptiv-controller-v1.0.0.zip`).
3. Ship that archive to the buyer along with a link or copy of:
   - `GETTING_STARTED.md` (this file).
   - `licensing_plan.md` for the high-level commercial terms.
4. Instruct the buyer to treat `GETTING_STARTED.md` as their installation guide and `licensing_plan.md` as the summary of what they can and cannot do.

The rest of the documentation in `docs/` (human and assistant guides, happy paths, architecture notes, and the proof-of-concept writeup) is there to help both you and the buyer get maximum value from the controller over time.
   - `git add .`
   - `git commit -m "Initial commit from Adaptiv Controller bundle"`
   - `git push -u origin main`

From this point on, you own the repo and can customize it as you like for your own use.
