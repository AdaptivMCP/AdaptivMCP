# UPGRADE_NOTES: Installing, upgrading, and rolling back the Adaptiv Controller GitHub MCP server

This document explains how to install new versions of the Adaptiv Controller GitHub MCP server, how to upgrade safely, and how to roll back if something goes wrong. It is written for operators and power users who run the server on platforms like Render and connect it to one or more Adaptiv Controller instances in ChatGPT.

You should read this together with:

- `docs/SELF_HOSTED_SETUP.md` – initial deployment and configuration.
- `docs/WORKFLOWS.md` – how assistants are expected to behave when using this server.
- `docs/ARCHITECTURE_AND_SAFETY.md` – the safety model, default branches, and write gating.

This guide focuses specifically on **version changes** and deployment practices for the 1.0 line and beyond.

## 1. Where version information lives (1.0 and later)

For the 1.0 release, versioning is wired into the repo itself. Treat these as a single source of truth:

- `pyproject.toml` – `project.version` (for example `1.0.0`).
- `CHANGELOG.md` – human-readable notes for each released version (starting at `1.0.0`).
- `cli.py` – a small CLI that reads the version from `pyproject.toml`.
- Git tags – recommended tags follow the pattern `v1.0.0`, `v1.0.1`, `v1.1.0`, and so on.

To confirm the version in any environment where the repo is available (local dev, a Render shell, or the controller workspace), run:

```bash
python cli.py --version
```

For the 1.0 release you should see `1.0.0`. If the reported version and `CHANGELOG.md` disagree with the tag or branch you believe is deployed, stop and resolve that mismatch before doing further work.

> Assistants using this server must run `python cli.py --version` at the start of a new ChatGPT session (see `docs/WORKFLOWS.md`) and refresh key docs from `main` so they are aligned with the version you actually have deployed.

---

## 2. How to think about versions

At a high level you should treat the MCP server like any other production service:

- Keep a clear distinction between **staging** and **production**.
- Pin production to a tag or stable branch, not to a constantly-moving `main`.
- Use small, well-understood increments when upgrading.
- Have a simple, well-practiced rollback plan.

The rest of this document describes how to put those principles into practice.

> Meta tools for upgrades: when validating a new version from ChatGPT, use:
> - `get_server_config` to confirm effective configuration (write gating, branch defaults, timeouts).
> - `list_all_actions` to ensure all tools are registered as expected.
> - `ping_extensions` to verify `extra_tools.py` and other extensions are loaded.

---

## 3. Installing a fresh deployment

For a brand new deployment (no existing MCP service), follow `SELF_HOSTED_SETUP.md` and then adopt the upgrade/rollback practices in this document from day one.

Recommended initial setup:

1. **Create a staging service**
   - In Render, create a Web Service for staging (for example `adaptiv-controller-github-mcp-staging`).
   - Point it at your repo (or fork) on a branch such as `main` or `staging`.
   - Configure environment variables (`GITHUB_TOKEN`, `GITHUB_MCP_CONTROLLER_REPO`, `GITHUB_MCP_CONTROLLER_BRANCH`, `GITHUB_MCP_AUTO_APPROVE`, HTTP tuning knobs).

2. **Create a production service**
   - Duplicate the staging service’s configuration into a second Web Service (for example `adaptiv-controller-github-mcp-prod`).
   - Pin it to a more stable reference (for example a tag or a dedicated `prod` branch).

3. **Verify both services**
   - Use `/healthz` on each service.
   - From ChatGPT, connect the staging service first and run:
     - `get_server_config`
     - `list_all_actions`
     - A small `get_file_contents` call against a known repo.
   - Once staging is green, connect production with the same steps.

Working this way from the beginning will make upgrades and rollbacks straightforward.

---

## 4. Upgrading to a new version (staging first)

When you want to upgrade the MCP server (for example after merging new tools or safety improvements), use a **staging-first** flow:

1. **Tag or otherwise identify the new version**
   - Create a Git tag (for example `v1.0.1`) at the commit you plan to deploy.
   - Alternatively, use a dedicated `release/x.y` branch if you prefer branch-based deployments.

2. **Update the staging service**
   - In Render, edit the staging Web Service and change the deployed branch/tag to the new version (for example from `v1.0.0` to `v1.0.1`).
   - Redeploy or trigger a manual deploy.

3. **Run smoke tests on staging**
   - From ChatGPT, connect the staging MCP server.
   - Run a small set of smoke tests using your Adaptiv Controller, for example:
     - `get_server_config` and `list_all_actions`.
     - A simple docs-only change (branch → edit → PR) against a test repo.
     - `run_command` and `run_tests` on the controller repo or a sample project.
   - Confirm that:
     - The controller contract looks correct.
     - Tools behave as expected.
     - Tests pass in the workspace.

4. **Promote to production**
   - Once staging is green, apply the same tag/branch update to the production Web Service.
   - Redeploy production.
   - Re-run a minimal smoke test in production (for example `get_server_config` and a single `get_file_contents` call).

If anything fails during these steps, stop and roll back (see the next section).

---

## 5. Rolling back to a previous version

If an upgrade causes problems, the rollback strategy should be as simple as possible. The exact steps depend on how you pinned versions originally.

### 5.1 If you deploy from tags

1. **Identify the last known-good tag**
   - For example, if `v1.0.1` is broken and `v1.0.0` was stable, you want to go back to `v1.0.0`.

2. **Update the production service**
   - In Render, change the deployed reference from the new tag back to the last known-good tag.
   - Redeploy.

3. **Verify after rollback**
   - Hit `/healthz`.
   - From ChatGPT, run a minimal smoke test to confirm the server is functional.

### 5.2 If you deploy from a branch

If you are deploying from a branch such as `prod` or `main`:

1. **Use Git to reset or revert**
   - Option A: reset the branch to the previous good commit.
   - Option B: revert the problematic commit(s) with `git revert`.

2. **Redeploy the service**
   - Once the branch points at the known-good commit, trigger a deploy in Render.

3. **Verify after rollback**
   - Same as above: `/healthz` and a small smoke test from ChatGPT.

In all cases, document the incident in your controller repo (for example using an issue that links to the problematic commit and the rollback steps you took).

---

## 6. Verifying upgrades with tests and health checks

Every upgrade should include at least three kinds of checks:

1. **Server-level health**
   - `/healthz` responds with a healthy status.
   - Metrics do not show abnormal spikes in errors, timeouts, or rate limiting.

2. **Workspace-level tests**
   - Use `run_command` and `run_tests` in the workspace to validate the controller repo and any key projects you care about.
   - For example, on the controller repo itself:
     - `run_tests` with `pytest -q`.

3. **Controller-level workflows**
   - Use your Adaptiv Controller to run a few realistic workflows:
     - Docs-only change via branch → edit → PR.
     - Small code change with corresponding test update.
     - Issue creation and PR commenting.

If any of these checks fail, treat the upgrade as incomplete and either fix the problem or roll back.

---

## 7. Recommendations for Render and similar platforms

When running on Render (or similar PaaS providers):

1. **Pin to tags or stable branches**
   - Avoid deploying directly from a constantly moving `main` branch in production.
   - Prefer tags (for example `v1.0.x`) or a dedicated `prod` branch that you update only after staging is green.

2. **Use separate staging and production services**
   - This lets you test a new version in staging without risking production.
   - You can run the same controller configuration against both services by switching MCP URLs in ChatGPT when testing.

3. **Leverage built-in health checks**
   - Point Render's health check at `GET /healthz`.
   - Configure a sensible timeout and failure threshold.

4. **Keep environment variables in sync**
   - Use the same set of env vars in staging and production.
   - Differences should be intentional (for example different GitHub tokens, different controller repos or branches).

5. **Document your rollback plan**
   - In your internal runbook (or in `docs/OPERATIONS.md`), write down exactly how to change the deployed tag/branch and redeploy.
   - Practice a rollback at least once in a non-critical environment.

---

## 8. Keeping this document up to date

As you add versioning metadata, change deployment patterns, or introduce new environments, make sure to update this file so it remains an accurate reflection of how you operate the MCP server.

In particular, revisit this document when you:

- Introduce new release tags or a `CHANGELOG`.
- Change how Render (or your hosting platform) is configured.
- Add staging environments, canary deployments, or blue/green strategies.
- Adjust write policies or workspace limits in ways that affect upgrades or rollbacks.

Treat `docs/UPGRADE_NOTES.md` as the single source of truth for how to move between versions of the Adaptiv Controller GitHub MCP server safely.
