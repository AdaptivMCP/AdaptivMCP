# Adaptiv Controller – Controller-in-a-box: Getting Started

_Last updated: 2025-12-12_

This guide is written for a **single developer** deploying the Adaptiv Controller GitHub MCP server from a source bundle (zip/tarball) and connecting it to a custom controller in ChatGPT.

## Prerequisites

You need:

- A GitHub account.
- A hosting provider (Render is the primary example here).
- A ChatGPT plan that supports MCP connectors / custom GPT tool use.

---

## 1. Create your private GitHub repository

1. Unpack the bundle you received (for example `adaptiv-controller-v1.0.0.zip`).
2. Create a new **private** GitHub repository (for example `my-adaptiv-controller`).
3. Push the unzipped contents:

```bash
cd adaptiv-controller-v1.0.0

git init

git add .

git commit -m "Initial commit from Adaptiv Controller bundle"

git branch -M main

git remote add origin git@github.com:<your-username>/<your-repo>.git

git push -u origin main
```

From this point on, you own the repo and can customize it for your environment.

---

## 2. Create a GitHub token

The MCP server needs a GitHub token to call the GitHub API.

Recommended:

- Prefer a **fine-grained** PAT scoped only to the repos you plan to manage.
- If you want workflow inspection tools, include the equivalent of `workflow` scope.

Do **not** commit your token to Git.

---

## 3. Deploy on Render

1. In Render: **New → Web Service**.
2. Select the repository you created above.
3. Render should detect the `Dockerfile`.
4. Set environment variables (start from `.env.example`). Minimum set:

- `GITHUB_PAT` (or `GITHUB_TOKEN`)
- `GITHUB_MCP_CONTROLLER_REPO=<your-username>/<your-repo>`
- `GITHUB_MCP_CONTROLLER_BRANCH=main`
- `GITHUB_MCP_AUTO_APPROVE=false` (recommended)
- `PORT=8000`

Once deployed, verify:

- `https://<your-service>.onrender.com/healthz`

---

## 4. Connect ChatGPT to your MCP server

In ChatGPT’s connector / MCP settings:

- Add a new MCP server pointing at `https://<your-service>.onrender.com`.

In a new chat with your controller, run:

- `get_server_config`
- `list_all_actions(include_parameters=true)`
- `validate_environment`

---

## 5. Create your personal controller

1. Create a custom GPT / assistant.
2. Paste `docs/assistant/CONTROLLER_PROMPT_V1.md` into its instructions.
3. Ensure the GPT is allowed to use your MCP server.
4. Optionally add a preferences file and tell your controller to read it:

- `docs/adaptiv/preferences.md`

---

## 6. Smoke test

Run a low-risk end-to-end test:

- Create a feature branch
- Make a tiny docs change
- Run `run_quality_suite` (or at least `run_tests`)
- Open a PR

Reference playbook: `docs/assistant/ASSISTANT_HAPPY_PATHS.md`.
