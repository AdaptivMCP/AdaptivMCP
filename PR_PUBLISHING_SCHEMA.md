# Pull Request Publishing Schema for Joey's GitHub Connector

This document defines the **canonical workflow and schema** every assistant must follow when creating PRs using the **Joey's GitHub** MCP server.

The goal is:

1. Consistent, predictable PRs.
2. Minimal surprises or breakages for Joey.
3. Clear traceability from assistant thought process to diff to tests to PR metadata.

This doc assumes:

- You are using the **Joey's GitHub MCP server**, not the built-in GitHub connector.
- The target repo is accessible via `Proofgate-Revocations/...` or other repos Joey owns.
- You treat `main` as protected: everything goes through PRs.

---

## 1. Pre-flight: understanding the server and repo

Before making any changes, assistants must:

1. Call `get_server_config`
   - Purpose: understand server settings and whether writes are allowed.
   - Read: `write_allowed`, http timeouts, concurrency limits, sandbox flags.
   - If `write_allowed` is false, do not attempt write tools until Joey explicitly approves enabling writes.

2. Call `list_write_tools`
   - Purpose: discover what write tools are available and how they are intended to be used.
   - Use this to confirm which tools exist and which are considered high-level vs low-level.

3. Call `get_repository`
   - Purpose: confirm repo metadata and default branch (usually `main`).

4. Call `list_branches`
   - Purpose: see what branches already exist and avoid name collisions.
   - Recommended branch prefix: `ally/<scope>-<short-description>`, for example `ally/mcp-connector-docs`.

---

## 2. Enabling write actions

The server can gate writes with `authorize_write_actions` and internal `write_allowed` state.

- At the start of a session where you expect to write:
  1. Call `get_server_config`.
  2. If `write_allowed` is false, do not bypass or work around it.
  3. Only if Joey has requested changes and is aware of writes, call `authorize_write_actions(approved=true)`.
  4. Re-check `get_server_config` to confirm `write_allowed` is now true.

- If any write tool returns a write-not-allowed error, stop and explain the failure to Joey before trying again.

---

## 3. Canonical PR workflows

This section defines the standard flows assistants must follow.

### 3.1 Flow A: small single-file change

Use this when you are editing one file and the change is modest in size.

Steps:

1. Read the file with `get_file_contents(full_name, path, ref=<default_branch>)`.
2. Explain to Joey what you will change in plain language.
3. Prepare the full updated file content (avoid patch juggling).
4. Either:
   - Use `apply_text_update_and_commit` on a dedicated branch, then `create_pull_request`, or
   - Use `update_files_and_open_pr` with a single-file entry for a one-shot commit+PR.
5. Confirm the PR response contains the branch and pull request details.
6. Report the PR link, summary of changes, and test status to Joey.

### 3.2 Flow B: multi-file change

Use this when you are editing multiple files as part of one logical change.

1. Read all affected files (via `fetch_files` or repeated `get_file_contents`).
2. Plan per-file changes in bullets and share with Joey.
3. Provide the updated content for each file.
4. Call `update_files_and_open_pr` with the file list and PR metadata.
5. Split changes into multiple PRs if the change is too large or touches unrelated concerns.

### 3.3 Flow C: new document from a stub

Use this when Joey has created a blank file or minimal stub on main and you want to fill in the content.

1. Confirm the stub exists with `get_file_contents` or `fetch_files`.
2. Draft the full document content in the conversation and get Joey's approval.
3. Publish via either:
   - `apply_text_update_and_commit` + `create_pull_request`, or
   - `update_files_and_open_pr` if you prefer a single one-shot call.
4. In the PR body, clearly state that this is a new document from a stub and explain how assistants should use it.

### 3.4 Flow D: running tests

Use `run_tests` or `run_command` when you changed code or tests and need to validate the suite.

1. Decide whether to run tests before or after opening the PR, based on Joey's guidance.
2. Use `run_tests` or `run_command` with an optional `patch` that mirrors the change you are committing so the run matches the PR.
3. Inspect the command result for exit code and output.
4. If tests fail, include failure details in your report and ask Joey how to proceed.

---

## 4. PR body schema

Every assistant-created PR must follow this schema in the PR body.

1. Summary

- 2 to 4 short bullets describing what the PR does.
- Focus on behaviour, not low-level implementation detail.

2. Motivation / Context

- Why this change is being made.
- Link back to the request or scenario from the ChatGPT conversation.

3. Changes by file

- `path/to/file.py`
  - Bullet list of logical changes in that file.
- `docs/how_to_use_connector.md`
  - Bullet list of doc changes.

4. Implementation notes (optional)

- Important design decisions, trade-offs, or limitations.

5. Testing

One of:

- `- [x] Tests run: <command>` with a short outcome.
- `- [ ] Tests not run (reason: <short explanation>)`.

6. Risks and rollbacks

- Risks: bullet list of realistic risks.
- Rollback: how Joey can revert or disable the change (for example revert the PR).

7. Follow-ups (optional)

- Items that are out of scope for this PR but worth tracking as future work.

---

## 5. Error handling and guardrails

When using write tools, assistants must:

1. Handle empty edits

- If your update would produce no effective change, do not open a PR.
- Explain to Joey that the repo already matches the desired state.

2. Handle content drift

- Common causes: file content on main changed since you fetched.
- Recovery steps:
  1. Re-fetch the current version of the affected files.
  2. Rebuild the updated content from the latest version.
  3. Retry the commit/PR tool once.
  4. If it still fails, stop and describe the failure rather than brute-forcing.

3. Handle failing tests from workspace runs

- If tests fail, you must surface that to Joey.
- Include failing test names when available and key lines from the traceback.
- Ask whether to fix tests in the same PR or in a follow-up.

4. Handle GitHub API errors

- Examples: rate limits, permission issues, timeouts.
- Report the error message and status code.
- Do not retry aggressively; one or two retries at most.
- Ask Joey before attempting large batches again.

---

## 6. Tool selection guide

When deciding which tool to use:

1. For single-file changes, prefer:
   - `apply_text_update_and_commit` + `create_pull_request`, or
   - `update_files_and_open_pr` with a one-file payload.
2. Use `apply_patch_and_commit` when you have an explicit unified diff from `build_unified_diff` and want a patch-first workflow.
3. Use `update_files_and_open_pr` for multi-file changes that should land together as one reviewable PR.
4. Use `run_tests` or `run_command` when you need a full workspace for tests or custom commands.
5. Never push directly to main or use other connectors to modify the same repo in the same session.

---

## 7. Example PR body template

Assistants should use a PR body like this and adapt as needed:

```markdown
## Summary

- Short bullet one
- Short bullet two

## Motivation / Context

- Explain what Joey asked for and why this PR exists.

## Changes by File

- `main.py`
  - Describe the logical changes in this file.
- `docs/how_to_use_connector.md`
  - Describe doc changes here.

## Implementation Notes

- Any notable design decisions, trade-offs, or caveats.

## Testing

- [x] Tests run: `pytest`
  - All tests passed via run_tests.
- [ ] Tests not run (reason: N/A)

## Risks & Rollback

- Risks:
  - Bullet list of realistic risks.
- Rollback:
  - Revert this PR via the GitHub UI if issues occur.

## Follow-ups

- Optional bullets for future work that is out of scope for this PR.
```

---

## 8. Session discipline

Every assistant using this connector should:

1. Start each session by:
   - Calling `get_server_config` and `list_write_tools`.
   - Confirming they understand what the server can do in that session.
2. Clearly narrate:
   - What repo and branch they are targeting.
   - What files they will touch.
   - Which tools they plan to use.
3. Use this schema for every PR:
   - No ad-hoc PR formats.
   - No quick fixes pushed directly without a PR.
