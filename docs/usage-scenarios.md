# Adaptiv MCP usage scenarios

This document highlights practical ways to use Adaptiv MCP in day-to-day operations. Each scenario includes a short objective, when to use it, and a typical flow.

## Scenario 1: Daily GitHub project hygiene

**Objective:** Keep repos clean, issues triaged, and PRs moving.

**When to use:** Daily/weekly maintenance or when a project starts accumulating stale issues/PRs.

**Typical flow:**

1. Use the GitHub tools to list open issues and pull requests.
2. Label or comment on items that need owner follow-up.
3. Close or merge items that meet criteria.
4. Summarize outcomes for the team.

**Why Adaptiv MCP helps:** The GitHub toolset centralizes routine repo tasks without leaving your chat or automation workflow.

## Scenario 2: Release coordination with workspace mirror

**Objective:** Prepare and validate release changes before opening a PR.

**When to use:** Before a release cut, hotfix, or coordinated change that needs review.

**Typical flow:**

1. Use the workspace mirror tools to fetch the repo.
2. Apply file edits, run tests, and generate release notes.
3. Commit changes in the mirror.
4. Open a PR via the GitHub tools.

**Why Adaptiv MCP helps:** The mirror-first workflow ensures you can run tests and apply patches in a real working copy, then open a PR once the changes are verified.

## Scenario 3: GitHub Actions debugging

**Objective:** Investigate failed CI runs quickly.

**When to use:** After a failing workflow run or unexpected build regression.

**Typical flow:**

1. List recent workflow runs for the target repo.
2. Pull logs for the failed run.
3. Create or update an issue with the failure summary.
4. Optionally trigger a new run once fixes are ready.

**Why Adaptiv MCP helps:** You can pull run logs and post updates to issues/PRs in a single workflow.

## Scenario 4: Render deployment oversight

**Objective:** Monitor deployments and react to incidents.

**When to use:** During active releases, incident response, or routine checks.

**Typical flow:**

1. List Render services and recent deploys.
2. Fetch deploy logs for anomalies.
3. Trigger a rollback or restart if needed.
4. Record status updates in a GitHub issue or incident log.

**Why Adaptiv MCP helps:** The Render toolset brings deployment actions and logs into the same operational channel as repo management.

## Scenario 5: Incident response with cross-tool coordination

**Objective:** Coordinate changes across GitHub and Render during incidents.

**When to use:** Production issues that require code changes and rapid deploys.

**Typical flow:**

1. Create an incident issue and assign owners.
2. Patch code in the workspace mirror and open a PR.
3. Merge after validation and trigger a Render deploy.
4. Monitor logs and document resolution steps.

**Why Adaptiv MCP helps:** It bridges code changes, deploy actions, and documentation in a single MCP server.

## Scenario 6: Connector readiness checks

**Objective:** Validate that the MCP server is healthy and discoverable.

**When to use:** After deployment, configuration changes, or proxy updates.

**Typical flow:**

1. Check `/healthz` for runtime health.
2. Query `/tools` and `/resources` for discovery.
3. Inspect `/ui.json` to verify base-path aware URLs.

**Why Adaptiv MCP helps:** The diagnostic endpoints surface exactly what connectors need to attach safely.

## Scenario 7: Governance and write gating

**Objective:** Keep control over write-capable actions in shared environments.

**When to use:** Multi-user environments or compliance-sensitive orgs.

**Typical flow:**

1. Keep write gating enabled in configuration.
2. Require explicit approvals for write-capable tools.
3. Track approvals through your operational process.

**Why Adaptiv MCP helps:** The server separates read/write actions and supports explicit approval workflows.

---

Want another scenario? Add it by following the same structure: **Objective**, **When to use**, **Typical flow**, and **Why Adaptiv MCP helps**.
