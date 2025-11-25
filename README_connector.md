# Joey’s GitHub MCP Connector

This document explains how to use the **Joey’s GitHub** MCP connector safely and effectively from within ChatGPT.

It is intended for assistants/agents that call MCP tools, not for end-users.

---

## 1. Endpoint and environment

### MCP endpoint

Use this SSE endpoint in the connector configuration:

```text
https://github-mcp-chatgpt.onrender.com/sse
Authentication for GitHub is handled server-side via a personal access token (GITHUB_PAT / GITHUB_TOKEN) and is not exposed to the MCP client.

Write gating
The server has a write gate:

WRITE_ALLOWED is initialized from the env var GITHUB_MCP_AUTO_APPROVE:

1 → write tools enabled by default.

0 → write tools disabled by default.

You can also toggle this at runtime via:

jsonc
Copy code
// Tool: authorize_write_actions
{
  "approved": true  // or false
}
Most write tools will fail with a clear error if writes are disabled.

2. Tool categories
2.1 Control
authorize_write_actions(approved: bool = True)

Turn write tools on/off for the current process.

Use if you need to explicitly disable writes or re-enable them.

2.2 Repository inspection / reads
Non-mutating tools; safe to call any time.

get_rate_limit()

Returns GitHub rate limit info for the configured token.

get_repository(full_name)

Example: "Proofgate-Revocations/CEO".

list_branches(full_name, per_page=100, page=1)

get_file_contents(full_name, path, ref="main")

Decodes base64 content from GitHub to text.

fetch_files(full_name, paths, ref="main")

Fetch multiple files concurrently.

Responses are truncated to avoid huge payloads.

graphql_query(query, variables)

fetch_url(url)

Fetch arbitrary HTTP/HTTPS URLs.

Response text is truncated for size safety.

2.3 GitHub Actions
Read-only unless you explicitly trigger workflows.

list_workflow_runs(full_name, branch?, status?, event?, per_page, page)

get_workflow_run(full_name, run_id)

list_workflow_run_jobs(full_name, run_id, per_page, page)

get_job_logs(full_name, job_id)

Logs truncated (~16k chars).

wait_for_workflow_run(full_name, run_id, timeout_seconds=900, poll_interval_seconds=10)

trigger_workflow_dispatch(full_name, workflow, ref, inputs?) (write)

trigger_and_wait_for_workflow(full_name, workflow, ref, inputs?, timeout_seconds=900, poll_interval_seconds=10) (write)

2.4 PR / issue management
list_pull_requests(full_name, state="open", head=None, base=None, per_page=30, page=1) (read)

compare_refs(full_name, base, head) (read)

Wraps GitHub “compare” API.

Returns summary + up to 100 files; patches are truncated.

Write tools:

create_pull_request(full_name, title, head, base="main", body=None, draft=False)

merge_pull_request(full_name, number, merge_method="squash", commit_title=None, commit_message=None)

close_pull_request(full_name, number)

comment_on_pull_request(full_name, number, body)

2.5 Branch / commit tools
Internal helpers:

_get_branch_sha(full_name, ref)

_resolve_file_sha(full_name, path, branch)

_perform_github_commit(...)

Exposed tools:

create_branch(full_name, new_branch, from_ref="main")

ensure_branch(full_name, branch, from_ref="main")

Creates branch if it does not exist.

commit_file_async(full_name, path, message, content=None, *, content_url=None, branch="main", sha=None)

Important rules:

Exactly one of content or content_url must be provided.

content_url must be an absolute http:// or https:// URL.

If it’s missing a scheme (e.g. "some/path"), the tool returns:

GitHubAPIError: content_url must be an absolute http(s) URL, got: '...'

If sha is omitted, it is auto-resolved.

The commit is performed in a background task.

Returns immediately:

json
Copy code
{
  "scheduled": true,
  "path": "README.md",
  "branch": "ally/some-branch",
  "message": "Update README"
}
update_files_and_open_pr(full_name, title, files[], base_branch="main", new_branch?, body?, draft=False)

High-level helper:

Ensures branch from base_branch.

Commits multiple files (content or content_url).

Opens a PR.

2.6 Workspace / full-env tools
These clone the repo into a temp directory on the MCP server.

run_command(full_name, ref="main", command="pytest", timeout_seconds=300, workdir=None)

run_tests(full_name, ref="main", test_command="pytest", timeout_seconds=600, workdir=None)

Thin wrapper over run_command.

apply_patch_and_open_pr(full_name, base_branch, patch, title, body=None, new_branch=None, run_tests_flag=False, test_command="pytest", test_timeout_seconds=600, draft=False)

Workflow:

Clone repo at base_branch.

git checkout -b <branch>.

Write patch (unified diff text) into mcp_patch.diff.

git apply --whitespace=nowarn mcp_patch.diff.

git commit -am "<title>".

Optionally run tests; if they fail, no push/PR.

git push branch to origin.

Open PR via create_pull_request.

Error handling:

This tool does not throw a ToolError on git failures.

Instead it returns a structured result:

json
Copy code
{
  "branch": "ally-patch-abc123",
  "tests": null,            // or test result dict if run
  "pull_request": null,     // or PR object on success
  "error": "git_apply_failed",
  "stderr": "error: corrupt patch at line 21\n..."
}
Possible error values include (non-exhaustive):

"git_checkout_failed"

"git_apply_failed"

"git_commit_failed"

"tests_failed"

"git_push_failed"

null when successful.

Callers must check error and should not assume a PR was opened unless error is null and pull_request is non-null.

3. Recommended workflows
3.1 Read-only analysis
Use when you’re inspecting code, CI, or repo state without modifying anything.

Typical sequence:

get_repository → confirm repo exists / basic info.

list_branches → discover available branches.

get_file_contents / fetch_files → load relevant code.

list_workflow_runs / get_workflow_run / get_job_logs → inspect CI.

No write tools involved.

3.2 Single-file change with a clean PR (recommended)
Use this pattern for small edits to a single file.

Choose a branch name, e.g. ally/<short-description>-<id>.

Create branch from main:

jsonc
Copy code
// create_branch
{
  "full_name": "Proofgate-Revocations/CEO",
  "new_branch": "ally/update-readme-1",
  "from_ref": "main"
}
Read the file and compute the updated full text (in ChatGPT).

Commit the new file contents:

jsonc
Copy code
// commit_file_async
{
  "full_name": "Proofgate-Revocations/CEO",
  "path": "README.md",
  "message": "Update README usage docs",
  "content": "<full updated README.md as a string>",
  "branch": "ally/update-readme-1"
}
Open a PR:

jsonc
Copy code
// create_pull_request
{
  "full_name": "Proofgate-Revocations/CEO",
  "title": "Update README usage docs",
  "head": "ally/update-readme-1",
  "base": "main",
  "body": "Explain the new workflow and connector usage.",
  "draft": false
}
3.3 Multi-file change with update_files_and_open_pr (recommended)
Use when you are touching several files at once.

Example:

jsonc
Copy code
// update_files_and_open_pr
{
  "full_name": "Proofgate-Revocations/CEO",
  "title": "Implement HMAC + idempotency for /evidence/record",
  "files": [
    {
      "path": "app/evidence.py",
      "content": "<full updated app/evidence.py>",
      "message": "Implement HMAC + idempotency checks in evidence handler"
    },
    {
      "path": "tests/test_evidence.py",
      "content": "<full updated test file>",
      "message": "Add tests for HMAC + idempotency"
    }
  ],
  "base_branch": "main",
  "new_branch": "ally/evidence-hmac-idem-1",
  "body": "Implements HMAC validation and idempotency for /evidence/record.",
  "draft": false
}
The tool will:

Ensure ally/evidence-hmac-idem-1 exists from main.

Commit both files.

Open a PR.

3.4 Patch-based change with apply_patch_and_open_pr (advanced)
Use this only if you truly need patch semantics.

Requirements:

patch must be a valid unified diff, e.g.:

diff
Copy code
diff --git a/app/evidence.py b/app/evidence.py
index 1234567..89abcde 100644
--- a/app/evidence.py
+++ b/app/evidence.py
@@ -10,6 +10,9 @@ def record_evidence(...):
-    # old behavior
+    # new behavior
+    validate_hmac(...)
+    ensure_idempotency(...)
Example call:

jsonc
Copy code
// apply_patch_and_open_pr
{
  "full_name": "Proofgate-Revocations/CEO",
  "base_branch": "main",
  "patch": "<unified diff text>",
  "title": "Security: wire HMAC + idempotency into /evidence/record",
  "body": "Implements HMAC validation and idempotency on the evidence endpoint.",
  "new_branch": "ally/evidence-hmac-idem-wire-1",
  "run_tests_flag": false,
  "draft": false
}
Then inspect the result:

If:

json
Copy code
"error": null,
"pull_request": { ... }
→ PR was opened successfully.

If:

json
Copy code
"error": "git_apply_failed",
"stderr": "error: corrupt patch at line 21\n..."
→ The patch is malformed. Do not call create_pull_request with that branch name; the branch will not exist remotely.

3.5 Running tests or commands
Use run_tests for common cases:

jsonc
Copy code
{
  "full_name": "Proofgate-Revocations/CEO",
  "ref": "ally/evidence-hmac-idem-wire-1",
  "test_command": "pytest",
  "timeout_seconds": 600,
  "workdir": null
}
Use run_command for arbitrary commands:

jsonc
Copy code
{
  "full_name": "Proofgate-Revocations/CEO",
  "ref": "ally/evidence-hmac-idem-wire-1",
  "command": "pytest tests/test_evidence.py -q",
  "timeout_seconds": 600,
  "workdir": null
}
Outputs include:

exit_code

timed_out

stdout (truncated)

stderr (truncated)

4. Common error patterns and how to handle them
GitHub 422 Validation Failed on create_pull_request

Causes:

head branch does not exist remotely.

Or head has no commits ahead of base.

Or a PR already exists for that head → base.

Assistant behavior:

Before calling create_pull_request, ensure:

A commit was made to the branch (commit_file_async or update_files_and_open_pr).

Do not call create_pull_request after apply_patch_and_open_pr returns an error (the branch was not pushed).

git apply failed: error: corrupt patch in apply_patch_and_open_pr

Cause:

The patch is not valid unified diff (bad hunk headers, incorrect line counts, truncated diff, etc.).

Assistant behavior:

Inspect result["error"] and result["stderr"].

Do not create a PR for this branch.

Optionally regenerate a smaller/cleaner diff or fall back to update_files_and_open_pr.

content_url must be an absolute http(s) URL in commit_file_async

Cause:

content_url is a bare path or missing scheme.

Assistant behavior:

Either:

Use content instead, passing the full file text, or

Fix content_url to be an https://... URL.

5. Behavioral guidelines for assistants
Prefer file-based workflows (commit_file_async, update_files_and_open_pr) over patch-based workflows unless you really need diffs.

For each change:

Work on a dedicated ally/... branch.

Make at least one commit before opening a PR.

Always inspect tool results:

For apply_patch_and_open_pr, check error and pull_request.

For run_tests / run_command, check exit_code and timed_out.

Keep outputs small to avoid MCP connector timeouts:

Avoid requesting very large file sets in a single fetch_files call.

Be aware that logs and content are truncated by design.