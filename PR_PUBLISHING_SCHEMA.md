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
3. Generate a unified diff (standard git diff format) targeting the default branch.
4. Call `apply_patch_and_open_pr` with:
   - `full_name`
   - `base_branch` (default branch, usually `main`)
   - `patch` (your unified diff)
   - `title` and `body` (see section 4)
   - `new_branch` (ally/<scope>-<short-description>)
   - `run_tests_flag` true for code changes, false for trivial docs.
5. Confirm `error` is null and `pull_request` contains number and url.
6. Report the PR link, summary of changes, and test status to Joey.

### 3.2 Flow B: multi-file change

Use this when you are editing multiple files as part of one logical change.

1. Read all affected files (via `fetch_files` or repeated `get_file_contents`).
2. Plan per-file changes in bullets and share with Joey.
3. Generate a single multi-file unified diff.
4. Call `apply_patch_and_open_pr` with that diff.
5. Split changes into multiple PRs if the diff is too large or touches unrelated concerns.

### 3.3 Flow C: new document from a stub

Use this when Joey has created a blank file or minimal stub on main and you want to fill in the content.

1. Confirm the stub exists with `get_file_contents` or `fetch_files`.
2. Draft the full document content in the conversation and get Joey's approval.
3. Generate a diff that replaces the stub content with the full document.
4. Use `apply_patch_and_open_pr` as in Flow A/B.
5. In the PR body, clearly state that this is a new document from a stub and explain how assistants should use it.

### 3.4 Flow D: running tests

Use `run_tests` or `run_command` when you changed code or tests and need to validate the suite.

1. Decide whether to run tests before or after opening the PR, based on Joey's guidance.
2. With `apply_patch_and_open_pr`, set `run_tests_flag` true and choose an appropriate `test_command` (for example `pytest`).
3. Inspect the `tests` field for exit code and output.
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

When using `apply_patch_and_open_pr` and related write tools, assistants must:

1. Handle empty diffs

- If your diff would produce no effective change, do not open a PR.
- Explain to Joey that the repo already matches the desired state.

2. Handle `git_apply_failed`

- Common causes: file content on main changed since you fetched; context mismatch in the patch.
- Recovery steps:
  1. Re-fetch the current version of the affected files.
  2. Rebuild the patch based on the new content.
  3. Try `apply_patch_and_open_pr` again.
  4. If it still fails, stop and describe the failure rather than brute-forcing.

3. Handle tests failing from `apply_patch_and_open_pr`

- If tests fail and the tool reports `tests_failed`, you must surface that to Joey.
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

1. Prefer `apply_patch_and_open_pr` for code and doc changes that can be expressed as diffs.
2. Use `run_tests` or `run_command` when you need a full workspace for tests or custom commands.
3. Use `commit_file_async` and `update_files_and_open_pr` sparingly, typically when Joey explicitly asks for that pattern.
4. Never push directly to main or use other connectors to modify the same repo in the same session.

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
