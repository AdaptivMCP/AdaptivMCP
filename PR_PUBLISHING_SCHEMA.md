# Pull Request Publishing Schema for Joey’s GitHub Connector

This document defines the **canonical workflow and schema** every assistant must follow when creating PRs using the **Joey’s GitHub** MCP server.

The goal is:

1. Consistent, predictable PRs.
2. Minimal surprises or breakages for Joey.
3. Clear traceability from “assistant thought process” → “diff” → “tests” → “PR metadata”.

This doc assumes:

- You are using the **Joey’s GitHub MCP server**, *not* the built-in GitHub connector.
- The target repo is accessible via `Proofgate-Revocations/...` or other repos Joey owns.
- You treat `main` as protected: everything goes through PRs.

---

## 1. Pre-flight: understanding the server and repo

Before making any changes, assistants **must**:

1. Call `get_server_config`

   - Purpose: understand server settings and whether writes are allowed.
   - You should read:
     - `write_allowed`
     - `http` timeouts
     - `concurrency` limits
     - `sandbox` configuration flags
   - If `write_allowed` is `false`, you **must not** attempt write tools until Joey explicitly approves enabling writes.

2. Call `list_write_tools`

   - Purpose: discover what write tools are available and how they are intended to be used.
   - Use this to confirm:
     - Which tools exist (`apply_patch_and_open_pr`, `update_files_and_open_pr`, `commit_file_async`, `run_tests`, etc.).
     - Which tools are considered “high-level” versus “low-level”.
   - Prefer the **highest-level** safe tool that matches what you need to do.

3. Call `get_repository`

   - Purpose: confirm repo metadata and default branch (usually `main`).
   - Use this to:
     - Confirm you’re working against the correct repo.
     - Learn the `default_branch` (don’t hardcode `main` unless the repo actually uses that).

4. Call `list_branches`

   - Purpose: see what branches already exist and avoid name collisions.
   - Recommended branch prefix format:
     - `ally/<scope>-<short-description>`
     - Example: `ally/mcp-connector-docs`, `ally/fix-apply-patch-logging`

---

## 2. Enabling write actions

### 2.1. Write gating

The server can gate writes with `authorize_write_actions` and internal `write_allowed` state.

- At the start of a session where you expect to write:
  1. Call `get_server_config`.
  2. If `write_allowed` is `false`, do **not** bypass or work around it.
  3. Only if Joey has requested changes and is aware of writes:
     - Call `authorize_write_actions(approved=true)` once for that session.
  4. Re-check `get_server_config` to confirm `write_allowed` is now `true`.

- If at any point a write tool returns a “write not allowed” error:
  - Stop immediately.
  - Explain the failure to Joey and ask before trying again.

---

## 3. Canonical PR workflows

This section defines the **standard flows** assistants must follow.

### 3.1. Flow A: small single-file change

Use this when:

- You are editing **one** file.
- The change is moderate in size (small function, small doc update, small refactor).

Steps:

1. **Read the file**
   - Use `get_file_contents(full_name, path, ref=<default_branch>)`.
   - Work from the latest version in the repo.

2. **Plan the change**
   - Explain to Joey what you will change, file by file, in plain language.
   - Confirm that the scope matches Joey’s request.

3. **Generate a unified diff**
   - Build a **unified diff** (standard `git diff` format) targeting the default branch.
   - Include only the necessary context around changed lines.
   - Do not include unrelated formatting or whitespace churn unless explicitly requested.

4. **Call `apply_patch_and_open_pr`**
   - Arguments:
     - `full_name`: `"owner/repo"`
     - `base_branch`: default branch, e.g. `"main"`
     - `patch`: unified diff you generated
     - `title`: short, imperative summary (`"Fix X"`, `"Document Y"`)
     - `body`: PR body following the schema in section 4
     - `new_branch`: optional; if omitted, the server may generate one
     - `run_tests_flag`: `true` for code changes, `false` for trivial docs
     - `test_command`: usually `"pytest"` (or repo-specific)
     - `draft`: set to `false` unless Joey wants drafts

5. **Inspect the response**
   - Confirm:
     - `error` is `None`.
     - `pull_request` is present and contains at least `number`, `html_url`, and `title`.
   - If `error` is set:
     - See section 5 (Error handling).
   - If tests were run:
     - Check `tests` payload for exit code and stdout/stderr.

6. **Report back to Joey**
   - Provide:
     - PR link / number.
     - High-level summary.
     - Test status.
     - Any warnings or follow-ups.

---

### 3.2. Flow B: multi-file change

Use this when:

- You are editing **multiple** files in one logical change.

Steps:

1. **Read all affected files**
   - Use `fetch_files` where convenient; otherwise, repeated `get_file_contents`.
   - Ensure the plan stays coherent and contained.

2. **Plan per-file changes**
   - Write a short bullet list:
     - For each file: what you will change and why.
   - Share this with Joey before generating diffs for large or risky changes.

3. **Generate a single multi-file patch**
   - Produce a unified diff that includes all file changes.
   - Maintain reasonable size; split changes into multiple PRs if:
     - The diff becomes hard to understand, or
     - The change logically breaks into independent chunks.

4. **Call `apply_patch_and_open_pr`**
   - Same as Flow A.
   - Use a branch name that reflects the broader scope, e.g.:
     - `ally/mcp-docs-and-logging`

5. **Treat the entire patch as atomic**
   - Avoid mixing unrelated changes in a single PR.
   - If the patch touches multiple concerns, split into multiple PRs.

---

### 3.3. Flow C: new document from an existing stub

Use this when:

- Joey has created a **blank file or minimal stub** on `main` (for example, a 1-line placeholder).
- You want to **fill in the content** by patching.

This is the preferred pattern for “brand new” docs when sandbox URL workflows are not configured.

Steps:

1. **Confirm the stub exists**
   - Use `get_file_contents` or `fetch_files` for the new path.
   - If the file does not exist, do **not** create it by guessing – ask Joey to create the stub.

2. **Design the document content**
   - Draft the full content in the conversation first.
   - Get Joey’s sign-off if the doc is long or opinionated.

3. **Generate a diff replacing the stub**
   - Build a unified diff that:
     - Matches the file’s current stub content in its context.
     - Replaces it with the full document body.
   - Apply the same PR workflow as Flow A/B via `apply_patch_and_open_pr`.

4. **PR body must clearly state**
   - That this is a new document based on a stub.
   - The purpose of the file and how assistants should use it going forward.

---

### 3.4. Flow D: running tests

Use `run_tests` or `run_command` when:

- You changed code or test files.
- You need to validate that the repo still passes its test suite.

Recommended workflow:

1. Before calling `apply_patch_and_open_pr`, consider:
   - If tests are quick and the change is risky, you may run tests in a workspace via `run_tests`.
   - If tests are long, coordinate with Joey on whether to run them.

2. When using `apply_patch_and_open_pr` with tests:
   - Set `run_tests_flag=true`.
   - Set `test_command` to the repo’s standard test command (e.g. `pytest`).
   - Set a reasonable `test_timeout_seconds` based on repo size and expected runtime.

3. Inspect test results
   - If tests fail:
     - Include failure details in the PR body / comment.
     - Do **not** silently ignore failures.
   - If tests succeed:
     - Include a short summary and clearly state what you ran.

---

## 4. PR body schema (what every PR must contain)

Every PR opened by an assistant must follow this schema in the **PR body**:

1. **Summary**
   - 2–4 short bullet points describing what the PR does.
   - Focus on behavior, not implementation detail.

2. **Motivation / Context**
   - Why this change is being made.
   - Reference the original request or scenario in ChatGPT (in plain language).

3. **Changes by file**
   - Format:
     - `path/to/file.py`
       - Bullet list of logical changes in that file.
     - `docs/HOW_TO_USE_CONNECTOR.md`
       - Bullet list of doc changes.

4. **Implementation notes (optional)**
   - Any important design decisions, limitations, or trade-offs.
   - Enough detail for Joey to review without re-deriving your reasoning from scratch.

5. **Testing**
   - Required section with one of:
     - `- [x] Tests run: <command>` plus short outcome.
     - `- [ ] Tests not run (reason: <short explanation>)`  
       Example reasons:
       - Repo has no tests.
       - Doc-only change with no code impact (state this explicitly).
       - Joey explicitly asked to skip tests.

6. **Risks & rollbacks**
   - Risks:
     - Bullet list of realistic risks (e.g. “may break X if Y assumption is false”).
   - Rollback strategy:
     - How Joey can revert if something goes wrong:
       - “Revert PR #NN via GitHub UI”
       - “Disable new behavior by removing XYZ config”

7. **Follow-ups (if any)**
   - Items that are out of scope for this PR but worth tracking.
   - Example:
     - “Add unit tests for new helper X in a follow-up PR.”
     - “Expand docs with more examples once this flow is stable.”

---

## 5. Error handling and guardrails

When using `apply_patch_and_open_pr` and related tools, assistants must:

1. **Detect and handle empty diffs**
   - If your generated patch would result in **no change**:
     - Do **not** open a PR.
     - Explain to Joey that the repo is already in the desired state.

2. **Handle `git_apply_failed`**
   - Common causes:
     - File content changed on `main` since you fetched.
     - Context mismatch in the patch.
   - Required recovery steps:
     1. Re-fetch the current version of the affected files.
     2. Re-generate the patch based on the new content.
     3. Try again with a fresh `apply_patch_and_open_pr` call.
     4. If it still fails, describe the failure and stop rather than brute-forcing.

3. **Handle tests failing in `apply_patch_and_open_pr`**
   - If tests fail and the server returns a `tests_failed` error:
     - Do not push the branch unless the server explicitly allows it.
     - Include:
       - The failing test names (when available).
       - Key lines from the traceback (truncated sensibly).
     - Ask Joey whether to:
       - Fix tests in the same PR, or
       - Land the change knowingly with broken tests (should be rare and explicit).

4. **Handle GitHub API errors**
   - Examples:
     - Rate limit exceeded.
     - Permission issues.
     - Network timeouts.
   - When this happens:
     - Report the error message and any HTTP status.
     - Do not retry aggressively in loops; one or two retries at most.
     - Ask Joey before attempting large batches again.

---

## 6. Tool selection guide

When deciding which tool to use:

1. **Prefer `apply_patch_and_open_pr`** for:
   - Code changes.
   - Doc changes that are easily expressed as diffs.
   - Any change where you can reasonably generate a unified diff.

2. **Use `run_tests` / `run_command` when:**
   - You need to validate changes in a cloned workspace.
   - You require a custom test command or working directory.

3. **Use `commit_file_async` and `update_files_and_open_pr` sparingly:**
   - Only when:
     - Joey explicitly asks for it, or
     - There is a clear reason you cannot comfortably express the change as a diff.
   - Be mindful of payload size and avoid giant inline content unless Joey has accepted that trade-off.

4. **Never:**
   - Push directly to `main`.
   - Create branches or commits using other connectors when working on the same repo in the same session.
   - Modify repo content outside of what Joey requested.

---

## 7. Example PR body template

Assistants should use a PR body like this (adapt as needed):

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
  - All tests passed locally via `run_tests`.
- [ ] Tests not run (reason: N/A)

## Risks & Rollback

- Risks:
  - Bullet list of realistic risks.
- Rollback:
  - Revert this PR via GitHub UI if issues occur.

## Follow-ups

- Optional bullets for future work that is out of scope for this PR.

8. Session discipline

Finally, every assistant using this connector should:
	1.	Start each session by:
	•	Calling get_server_config and list_write_tools.
	•	Confirming they understand what the server can do in that session.
	2.	Clearly narrate:
	•	What repo and branch they are targeting.
	•	What files they will touch.
	•	Which tools they plan to use.
	3.	Use this schema for every PR:
	•	No ad-hoc PR formats.
	•	No “quick fixes” pushed directly without a PR.