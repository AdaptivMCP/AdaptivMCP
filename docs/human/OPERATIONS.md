# OPERATIONS: Runbook for incidents and common failures

This document is for people running the Adaptiv Controller GitHub MCP server for themselves. It describes how to triage and respond to common incidents, how to use the built-in tools and endpoints to debug problems, and how to adjust configuration safely during an incident.

If you are running the Adaptiv Controller server for yourself (for example on Render or another host), this is the place to look when something goes wrong. Read this together with:

- `docs/SELF_HOSTED_SETUP.md` for initial deployment and configuration.
- `docs/WORKFLOWS.md` for expected assistant behavior.
- `docs/UPGRADE_NOTES.md` for versioning, install, upgrade, and rollback flows.
- `CHANGELOG.md` and `pyproject.toml` for version numbers and release history.

---

## 1. High-level mental model

At a high level, the system has three layers that are relevant during an incident:

1. **Hosting platform** (for example Render)
   - Is the process running?
   - Are environment variables set correctly?
   - Are there recent deploys or rollbacks?

2. **MCP server** (this repo)
   - Is the HTTP process healthy? (`/healthz`)
   - Can it reach GitHub with the configured token?
   - Are tools and workspace commands behaving as expected?

3. **Controller and assistants** (ChatGPT side)
   - Is the controller using `get_server_config`, `validate_environment`, `terminal_command`, and `run_tests` correctly?
   - Are prompts configured to follow safe branching and testing workflows?

Most incidents can be narrowed down by checking these layers in order: hosting → MCP server → controller/assistant behavior.

When you are unsure which layer is at fault, start by calling these meta tools from the controller:

- `get_server_config`: Confirm controller repo, default branch, write gating, and HTTP settings.
- `list_all_actions`: Confirm that the tools you expect (including any recently added ones) are actually exposed.
- `validate_environment`: Check for missing tokens, misconfigured controller repo/branch, or suspicious timeout/concurrency values.
- `ping_extensions`: Verify that optional extension modules have been loaded and their tools registered.

These helpers quickly distinguish configuration problems from deeper bugs.

---

## 2. Quick triage checklist

When someone reports "GitHub via Adaptiv Controller is broken":

1. **Check /healthz**
   - Call `GET /healthz` on the MCP server.
   - Confirm:
   - If you suspect a version mismatch (for example after an upgrade), use `terminal_command` to run `python cli.py --version` in the controller repo workspace and compare it with `docs/UPGRADE_NOTES.md` and `CHANGELOG.md`.
     - `status` is `ok` or similar.
     - `github_token_present` is `true`.
     - `controller.repo` and `controller.default_branch` match your expectations.
   - Look at `metrics.github` for spikes in `errors_total`, `rate_limit_events_total`, or `timeouts_total`.

2. **Call validate_environment from the controller**
   - From ChatGPT, with the controller attached, call the `validate_environment` tool.
     - Missing or malformed `GITHUB_TOKEN`.
     - Mismatched `GITHUB_MCP_CONTROLLER_REPO` or `GITHUB_MCP_CONTROLLER_BRANCH`.
     - Suspicious HTTP timeout or concurrency settings.

3. **Check hosting logs**
   - In Render (or your platform), open the logs for the MCP service.
   - Look for:
     - Tracebacks or import errors at startup.
     - Repeated GitHub `401`, `403`, or `422` errors.
     - Signs of rate limiting or timeouts from GitHub.

4. **Reproduce via a minimal workflow**
   - In ChatGPT, create a simple test run with the controller that calls:
     - `get_server_config`
     - `list_all_actions`
     - A simple read tool such as `get_file_contents` on a known repo/file
   - If reads fail, focus on token/access issues.
   - If reads succeed but writes fail, focus on write gating, branch/ref settings, or GitHub restrictions (for example protection rules).

Once you know whether the incident is about availability, GitHub access, workspace commands, or controller behavior, use the sections below.

---

## 3. GitHub authentication and permissions issues

Symptoms:

- Tools fail with 401 or 403 errors.
- `/healthz` reports `github_token_present: false`.
- `validate_environment` marks token-related checks as `error`.

Actions:

1. **Verify the token in your hosting provider**
   - Ensure `GITHUB_TOKEN` is set as an environment variable.
   - Confirm that the token has not expired or been revoked.
   - For fine-grained tokens, confirm that the target repos are in scope.

2. **Check scopes**
   - For typical usage you should have at least `repo` scope (or fine-grained equivalent).
   - If issue or PR tools are failing, confirm the token can create and update issues and pull requests in the target repos.
   - Use `validate_environment` to confirm the token can push to the controller repository; a missing push permission will cause 403 errors when assistants try to commit or push changes.

3. **Rotate the token safely**
   - Generate a new token.
   - Update the hosting provider’s environment variable for `GITHUB_TOKEN`.
   - Redeploy or restart the MCP service.
   - Re-run `/healthz` and `validate_environment` to confirm the new token is active.

If authentication is still failing, capture the relevant log lines (without the token value) and attach them to an internal incident doc or issue.

---

## 4. Timeouts, rate limiting, and GitHub errors

Symptoms:

- Tools intermittently fail with timeout errors.
- `/healthz` metrics show spikes in `timeouts_total` or `rate_limit_events_total`.
- GitHub API responses include 429 (rate limiting) or repeated 5xx errors.

Actions:

1. **Confirm HTTP and concurrency settings**
   - Review environment variables related to HTTP timeouts and concurrency (for example, httpx timeout, max connections, and max concurrency).
   - If the controller is hammering GitHub with many concurrent calls, consider lowering concurrency or adding backoff in prompts/workflows.

2. **Check GitHub status**
   - If many requests are failing with 5xx codes, verify GitHub’s status page for ongoing incidents.

3. **Respond to rate limiting**
   - If `rate_limit_events_total` is high, consider:
     - Reducing bursty operations in controller prompts.
     - Spreading heavy workflows out over time.

4. **Investigate recurring 422 errors**
   - 422 from GitHub often indicates validation problems (for example invalid branches, duplicate PRs, or mismatched SHAs).
   - See the next section on branch/PR issues for guidance.

---

## 5. Branch, PR, and workspace issues

### 5.1 Branch/ref problems

Symptoms:

- PR creation fails with 422 errors.
- Tools complain about missing or invalid refs.
- Changes end up on unexpected branches.

Actions:

1. **Check controller repo branch defaults**
   - Confirm `GITHUB_MCP_CONTROLLER_BRANCH` points to the correct default for the controller repo.
   - Use `get_server_config` to inspect the current `controller.default_branch`.

2. **Check `_effective_ref_for_repo` behavior (mental model)**
   - For the controller repo, missing refs or `main` may be remapped to your configured default branch.
   - For other repos, missing refs default to `main`.

3. **Inspect existing branches and PRs**
   - Use `list_pull_requests` and GitHub UI to confirm whether a PR for the same branch already exists.
   - If needed, close or merge old PRs and delete stale branches before retrying.

### 5.2 Workspace command failures (terminal_command / run_tests)

Symptoms:

- `terminal_command` fails with missing dependencies or import errors.
- `run_tests` fails immediately due to environment issues.

Actions:

1. **Inspect command output and truncation flags**
   - Look at `exit_code`, `stdout`, `stderr`, and the `*_truncated` flags.
   - If output is truncated, consider re-running with more targeted commands (for example a single test module instead of the entire suite).

2. **Ensure project dependencies are installed in the workspace**
   - Use `terminal_command` to install dependencies inside the workspace, for example:
     - `pip install -r requirements.txt`
   - The workspace itself persists on disk between related commands, but commands typically run inside a temporary virtual environment. Install only what is necessary for the current repo and avoid relying on global state across unrelated sessions.

3. **Use smaller, focused commands for debugging**
   - Instead of running the entire test suite on every iteration, use `terminal_command` or `run_tests` with narrower scopes (for example a single test file).
If workspace commands consistently fail in the same way, capture `exit_code`, key parts of `stderr`, and the command arguments in an internal incident doc.

---

## 6. Misconfigurations and environment validation

The `validate_environment` tool is designed to catch common misconfigurations before you chase deeper issues.

Use it when:

- You deploy to a new environment (staging, prod, another region).
- You rotate tokens or change environment variables.
- You see repeated failures across many different tools.

`validate_environment` returns a structured report with checks like:

- GitHub authentication configured and valid.
- Controller repo and branch reachable.
- Logging and metrics hooks attached.
- HTTP timeouts and concurrency values in a sane range.

If you see `error` or `warning` levels in this report, address those first. Many "mysterious" failures are ultimately configuration problems that `validate_environment` can point out.

---

## 7. Adjusting tools and policies during an incident

Sometimes the safest response to an incident is to temporarily reduce what the controller can do.

Options include:

1. **Disable writes globally**
   - Call `authorize_write_actions(approved=False)` from the controller.
   - This will cause write tools (including `terminal_command`, `run_tests`, commit helpers, and issue tools) to fail fast with a clear error.
   - Use this when you suspect a misbehaving workflow or prompt is issuing unsafe write operations.

2. **Switch to manual approval mode**
   - In hosting configuration, remove or set `GITHUB_MCP_AUTO_APPROVE` to a falsey value.
   - Redeploy or restart the service.
   - Controllers must then call `authorize_write_actions(approved=True)` explicitly before writes will run.

3. **Future: per-tool allowlist/denylist**
   - Issue #138 tracks adding configuration to selectively disable specific write tools.
   - Once implemented, this runbook should be updated with examples of disabling tools like `delete_file` or `delete_remote_branch` while leaving safer tools enabled.

During any change to write policies, make sure to communicate to users of the controller that write capabilities may be temporarily restricted.

---

## 8. Rotating secrets and environment changes

When you need to rotate secrets or change environment variables:

1. **Plan the change**
   - Identify which variables will change (for example `GITHUB_TOKEN`, timeouts, concurrency limits).
   - Decide whether you will restart the service or roll out a fresh deploy.

2. **Apply the changes in your hosting provider**
   - Update the environment variables in Render (or equivalent).
   - Redeploy or restart the service.

3. **Verify after the change**
   - Call `/healthz` to ensure the service is up and the token is present.
   - Run `validate_environment` to confirm configuration is coherent.
   - Run a small smoke test via the controller (for example, a simple `get_file_contents` call).

If problems arise, use hosting logs plus the tools described in this document to roll back or further adjust configuration.

---

## 9. When to escalate or file an issue

You should file or update an issue in your controller repo when:

- You discover a recurring class of incident that is not yet covered by this runbook.
- You need new configuration knobs (for example, a tool-level denylist) to handle a class of problems.
- You identify a bug in the MCP server logic, tests, or safety model.

When filing an issue, include:

- A short description of the incident and observed behavior.
- Relevant `/healthz` snapshot fields (without secrets).
- High-level output from `validate_environment` (especially any errors or warnings).
- Summaries of GitHub error codes (for example 401/403/422/429).

Over time, keep `docs/OPERATIONS.md` updated as you gain more operational experience. Treat it as a living document that encodes how you run the Adaptiv Controller safely in production.