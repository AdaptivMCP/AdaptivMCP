# Adaptiv MCP Happy Paths & Usage Playbook

## 1) First-run sanity checks

### Happy path: Verify environment and tool availability
1. Ask ChatGPT to run `validate_environment`.
2. Confirm GitHub token, optional Render token, and workspace base directory are reported as healthy.
3. If healthy, ask for a quick tool inventory (`/tools` equivalent via MCP introspection).

**Example prompt to ChatGPT**
- “Use `validate_environment`, summarize any missing env vars, then list which tool groups are ready (GitHub, workspace, Render).”

---

## 2) Repository discovery and triage (GitHub API)

### Happy path: Understand a repo before making changes
1. Identify the target repo.
2. Fetch repository overview (default branch, visibility, metadata).
3. List recent open pull requests and issues.
4. Summarize top 3 actionable items.

**Example prompt**
- “For `<owner>/<repo>`, list open PRs and open issues, cluster them by theme, and recommend the best next engineering task.”

### Happy path: Read and comment on issues
1. Pull issue details.
2. Draft a clarifying comment.
3. Post comment through MCP.

**Example prompt**
- “Open issue #123 in `<owner>/<repo>`, summarize root cause hypotheses, and post a concise follow-up question to the issue.”

---

## 3) Workspace mirror bootstrap

### Happy path: Clone and prep local mirror for coding
1. Create/refresh workspace mirror for `<owner>/<repo>`.
2. Confirm current branch and clean git status.
3. Read key files (README, contribution docs, target module).

**Example prompt**
- “Clone or sync `<owner>/<repo>` into workspace, confirm I’m on the default branch with clean status, then show me the top files relevant to authentication.”

### Happy path: Fast code search in mirror
1. Use ripgrep-backed search tool on symbol/keyword.
2. Open matching files and summarize call graph.

**Example prompt**
- “Search for `validate_environment` in the workspace, map where it is defined and invoked, and identify the safest extension point.”

---

## 4) Safe file edits

### Happy path: Single-file bug fix
1. Read target file.
2. Apply focused edit.
3. Re-read modified section.
4. Explain change impact.

**Example prompt**
- “In workspace repo `<owner>/<repo>`, fix the null-check bug in `<path/file.py>` without refactoring unrelated code. Show a minimal diff and reasoning.”

### Happy path: Multi-file refactor with strict scope
1. Create small plan.
2. Edit file-by-file.
3. Keep interface compatibility.
4. Produce consolidated diff summary.

**Example prompt**
- “Refactor duplicate token resolution logic into one helper, update callers, and keep behavior identical. Limit changes to files under `github_mcp/`.”

---

## 5) Quality checks in the mirror

### Happy path: Run targeted tests first
1. Run narrow tests for changed module.
2. Fix failures.
3. Re-run the same tests.

**Example prompt**
- “Run only tests related to `workspace_tools/commit.py`, fix failures introduced by my change, and stop when that test subset passes.”

### Happy path: Run broader validation before commit
1. Execute broader test slice (or full suite if feasible).
2. Report pass/fail + known flakes.
3. Summarize risk.

**Example prompt**
- “Run the project’s standard test command and provide a concise release risk summary based on results.”

---

## 6) Branching, commit, push, and PR (mirror-first)

### Happy path: Feature branch workflow
1. Create a branch (`feat/...` or `fix/...`).
2. Stage all intended files.
3. Commit with clear message.
4. Push branch.
5. Open PR with body that includes summary, tests, and risk.

**Example prompt**
- “Create `fix/issue-123-null-guard`, commit all related changes, push, and open a PR linked to issue #123 with test evidence.”

### Happy path: Keep PR up to date
1. Fetch/rebase or merge default branch.
2. Resolve conflicts.
3. Re-run tests.
4. Push updated branch.

**Example prompt**
- “Sync my branch with `main`, resolve conflicts favoring current behavior, rerun tests, and update the PR description with conflict notes.”

---

## 7) Pull request operations (GitHub)

### Happy path: Reviewer support loop
1. Read review comments.
2. Apply requested edits in workspace.
3. Reply to each review thread with what changed.

**Example prompt**
- “Fetch unresolved review comments for PR #45, implement requested changes, and draft reply comments mapped 1:1 to each thread.”

### Happy path: Merge-ready checks
1. Validate CI status and review approvals.
2. Confirm branch up-to-date.
3. Merge PR with preferred strategy.

**Example prompt**
- “Check whether PR #45 is merge-ready; if yes, merge with squash and post a short release note comment.”

---

## 8) GitHub Actions workflows

### Happy path: Trigger a workflow_dispatch
1. List workflows.
2. Select target workflow.
3. Trigger dispatch with ref/inputs.
4. Track run status.

**Example prompt**
- “Dispatch `deploy.yml` on branch `release/1.2.0` with input `environment=staging`, then monitor until completion and summarize logs.”

### Happy path: Diagnose failed runs
1. Fetch failed run IDs.
2. Pull logs.
3. Identify first failing step.
4. Propose fix and patch.

**Example prompt**
- “For the latest failed workflow run in `<owner>/<repo>`, extract the first error, propose a minimal fix, apply it in workspace, and open a PR.”

---

## 9) Render operations

### Happy path: Service and deploy visibility
1. List Render services.
2. Show recent deploys for target service.
3. Identify latest healthy version.

**Example prompt**
- “List my Render services, then for `<service-id>` summarize the last 5 deploys with status and duration.”

### Happy path: Controlled restart and verification
1. Restart target service.
2. Watch deploy/log status.
3. Verify health endpoint.

**Example prompt**
- “Restart Render service `<service-id>`, monitor logs for startup errors, and confirm the `/healthz` endpoint is healthy.”

### Happy path: Rollback after bad deploy
1. Locate last known good deploy.
2. Trigger rollback.
3. Confirm recovery through logs + health checks.

**Example prompt**
- “Rollback `<service-id>` to the previous healthy deploy and provide a post-incident summary in 5 bullets.”

---

## 10) End-to-end release flow

### Happy path: Issue → code → tests → PR → merge → deploy
1. Select issue.
2. Implement in workspace.
3. Run tests.
4. Open PR.
5. Merge after approvals/CI.
6. Trigger deploy workflow or Render deploy.
7. Validate health.

**Example prompt**
- “Take issue #123 from triage through merge and deployment using Adaptiv MCP tools, pausing only if CI fails or human approval is required.”

---

## 11) High-value “assistant macros” you can reuse

### Macro A: “Daily maintainer sweep”
- Review open issues, stale PRs, and failed workflows.
- Produce prioritized action list.
- Draft suggested comments for top items.

### Macro B: “Safe hotfix path”
- Create hotfix branch from default.
- Apply minimal patch.
- Run targeted tests.
- Open PR with urgency context.
- Trigger deploy after merge.

### Macro C: “New contributor onboarding”
- Explain repo structure.
- Pick a good first issue.
- Guide branch setup and first commit.
- Draft PR checklist.

---

## 12) Best practices to preserve happy paths

- Keep prompts explicit about **repo**, **branch**, and **scope boundaries**.
- Ask for a **plan first**, then execution.
- Prefer targeted tests before full-suite tests.
- Require a concise **diff summary + risk note** before commit.
- Use mirror-first workflows for reproducibility.
- For production operations (Render), ask for **confirmation checkpoints** between restart/rollback/deploy steps.

---

## 13) Copy/paste prompt starter pack

- “Validate environment, then tell me exactly what Adaptiv MCP capabilities are available right now.”
- “Sync workspace for `<owner>/<repo>`, inspect issue #`<n>`, implement the fix, run related tests, and open a PR.”
- “Find the latest failed GitHub Actions run, diagnose root cause from logs, patch in workspace, and open a fix PR.”
- “Show Render deploy health for `<service-id>`, then restart safely and verify `/healthz`.”
- “Do a maintainer sweep: stale PRs, blocked issues, failed workflows, and recommended next actions.”


