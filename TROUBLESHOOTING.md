# TROUBLESHOOTING.md

Troubleshooting guide for Joey's GitHub MCP server and this repository.

This document is intended for assistants and humans who are trying to understand
and fix issues with the GitHub MCP deployment and tools, especially on Render
and in MCP-aware clients like ChatGPT.

## 1. Render service is failing to start

### Symptom

The Render deploy log shows something like:

- `ImportError: cannot import name 'tool' from 'fastmcp'`
- `ValueError: "FunctionTool" object has no field "write_action"`
- Or any exception thrown at module import time for `main.py`.

### Checks

1. Ensure you're deploying the **current** version of `main.py` from `main`.
2. Confirm Python version matches what this repo expects (Render uses 3.13.x).
3. Make sure `fastmcp` is installed from `requirements.txt` and you're not
   manually pinning an incompatible version.

### Fix

- Never edit `main.py` directly in Render.
- Always update it via this repo, then let Render rebuild and deploy.
- If you see `FunctionTool` attribute errors, you're probably on an old
  version of `main.py` that tried to mutate the tool object directly instead
  of using the `write_action` decorator metadata.

## 2. MCP tools can’t write (WriteNotAuthorizedError)

### Symptom

A tool call response contains an error similar to:

- `WriteNotAuthorizedError: write actions are currently disabled`

### Checks

1. Environment:

   - `GITHUB_MCP_AUTO_APPROVE` is unset or set to a false-y value (e.g. `0`).

2. Workflow:

   - You never called `authorize_write_actions(approved=True)` at the start
     of your MCP session.

### Fix

- Either:

  1. Set `GITHUB_MCP_AUTO_APPROVE=1` in Render to allow writes by default, or
  2. Call the `authorize_write_actions` tool with `{"approved": true}`
     before using write tools like `apply_patch_and_open_pr` or `run_tests`.

## 3. Git patch application fails (git_apply_failed)

### Symptom

`apply_patch_and_open_pr` returns a result with:

- `error: "git_apply_failed"`
- `stderr` mentioning `patch does not apply` or similar.

### Why this happens

- The unified diff you sent does not match the current contents of the repo.
- Common causes:

  - The file changed on `main` after you read it.
  - The diff was hand-written and the context lines don’t match exactly.
  - Line endings or spacing differ from what you assumed.

### Fix

1. Re-fetch the latest contents of the file(s) with `get_file_contents` or
   `fetch_files`.
2. Recompute the patch based on the **actual** content.
3. Keep patches small and focused (≤ 500 lines / 20k chars).
4. Try `apply_patch_and_open_pr` again once.

If the patch keeps failing, stop and surface the `stderr` to Joey for a
manual decision instead of brute-forcing more attempts.

## 4. Empty patches or no-op diffs are rejected (empty_patch / empty_diff)

### Symptom

`apply_patch_and_open_pr` returns a result with either:

- `error: "empty_patch"` and `stderr` explaining the patch body was empty or
  whitespace-only (guardrail before any git ops).
- `error: "empty_diff"` when the patch applied cleanly but produced no staged
  changes (no-op diff after application).

### Fix

- Rebuild the unified diff and confirm it contains the intended edits.
- Make sure the diff actually changes files; identical old/new hunks trigger
  `empty_diff` even if the patch text is non-empty.
- Avoid sending empty templates; both guardrails keep the workflow predictable
  and avoid creating useless branches.

## 5. Tests fail in apply_patch_and_open_pr (tests_failed)

### Symptom

`apply_patch_and_open_pr` returns a result with:

- `error: "tests_failed"`
- A `tests` object containing `exit_code`, `stdout`, and `stderr` from pytest.

### Fix pattern

1. Read the `stdout` / `stderr` from the `tests` field.
2. Summarize which tests failed and why.
3. Do **not** auto-edit large parts of the repo blindly to “fix” failures.
4. Propose targeted next steps (e.g. adjust a specific function or test) and
   wait for Joey’s confirmation before making more changes.

## 6. Git push fails (git_push_failed)

### Symptom

`apply_patch_and_open_pr` returns:

- `error: "git_push_failed"`
- `stderr` with git push output.

### Possible causes

- Branch protection rules on the target repo.
- Missing or invalid `GITHUB_PAT` in Render.
- Network or transient GitHub issues.

### Fix

1. Surface the full `stderr` in your assistant response.
2. Check:

   - `GITHUB_PAT` is set in Render and has `repo` + `workflow` scopes.
   - The branch you are pushing is not targeting a protected branch with
     disallowed direct pushes.

3. Do not retry the same push endlessly; wait for Joey to adjust settings or
   confirm the next step.

## 7. Rate limiting and GitHub API errors

### Symptom

Responses from tools like `get_rate_limit`, `get_repository`, or
`fetch_files` contain GitHub errors such as:

- `API rate limit exceeded for user`
- 4xx or 5xx status codes from `api.github.com`.

### Fix

1. Use `get_rate_limit` to inspect current limits and reset times.
2. Avoid spamming GitHub with unnecessary calls.
3. For assistants: batch file fetches with `fetch_files` where reasonable.

If rate limits are repeatedly a problem, Joey may need to adjust usage or
token scopes.

## 8. MCP connector configuration issues

### Symptom

ChatGPT (or another MCP client) cannot connect to Joey’s GitHub server at all.

### Checks

1. Connector URL:

   - Should be `https://github-mcp-chatgpt.onrender.com/sse`.
   - Path `/sse` is required; `/` alone will not speak MCP SSE.

2. Authentication:

   - In ChatGPT’s MCP configuration, **do not** configure OAuth or API keys
     for Joey’s GitHub.
   - The server authenticates to GitHub using `GITHUB_PAT` in the Render
     environment; the client does not need its own GitHub token.

3. Health check:

   - Visit `https://github-mcp-chatgpt.onrender.com/` to see the banner.
   - Visit `https://github-mcp-chatgpt.onrender.com/healthz` to see `OK`.

If `/` and `/healthz` are healthy but the MCP client still cannot connect,
double-check the MCP configuration in the client (URL, path, and name).

## 9. When in doubt

If you are an assistant:

- Do not keep retrying failing tools without changing anything.
- Always surface:

  - The tool name you called.
  - The arguments used (minus secrets).
  - The `error`, `stderr`, and any status fields.

If you are Joey:

- Check Render logs for stack traces or import errors.
- Use the existing tests (`pytest`) via the `run_tests` tool to validate
  changes before debugging in production.
