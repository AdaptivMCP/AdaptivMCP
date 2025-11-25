# Rules for Assistants – Joey’s GitHub MCP Server

This document defines the rules that all assistants must follow when using the **Joey’s GitHub** MCP server. These rules are designed to keep changes safe, reviewable, and compatible with the server and hosting environment.

---

## 1. Always use Joey’s GitHub MCP for Joey’s repos

1. Use the **Joey’s GitHub** MCP server as the primary way to access Joey’s repositories.
2. Do not mix this with other GitHub connectors for the same repo. All reads and writes should go through this MCP server so state is consistent and auditable.

---

## 2. Read before you write

1. Before changing any file, you must fetch the current contents from Joey’s GitHub MCP:
   - For a single file: `get_file_contents`.
   - For multiple files: `fetch_files`.
2. Never assume what is on `main` or any branch; always base patches on live data returned by the MCP tools.

---

## 3. Use patches for code changes

1. For code changes, the default workflow is:
   1. Read the current file(s) with `get_file_contents` or `fetch_files`.
   2. Compute the desired edits.
   3. Generate a **unified diff** (e.g. `git diff` style) against the current contents.
   4. Call `apply_patch_and_open_pr` with that diff.
2. Do **not** send full rewritten files for code unless Joey explicitly requests it.
3. Keep each patch small and focused:
   - Roughly ≤ 500 lines.
   - Roughly ≤ 20k characters.
4. If a change is large, split it into multiple smaller patches / PRs.

---

## 4. Use `content_url` only for docs and only when appropriate

1. For medium or large **documentation** files (`.md`, `.txt`, etc.), prefer the **sandbox + `content_url`** pattern:
   1. Write the file to the ChatGPT sandbox (e.g. `/mnt/data/ASSISTANT_GUIDE.md`).
   2. Call `commit_file_async` or `update_files_and_open_pr` with `content_url` set to that sandbox path.
2. The hosting layer rewrites the sandbox path into an internal HTTP(S) URL before it reaches the MCP server.
3. The MCP server enforces that `content_url` must be an absolute `http(s)` URL; do not try to bypass this.
4. For code, prefer patches (`apply_patch_and_open_pr`). Only use `content_url` for code if Joey explicitly instructs you to.

---

## 5. Avoid huge inline payloads

1. Do not send very large inline `content` strings in tool calls.
2. If you must send inline content:
   - Keep it small (e.g. short snippets, very small docs).
3. For anything larger:
   - Use unified diffs for code changes.
   - Use sandbox + `content_url` for docs.

---

## 6. Treat write tools as dangerous by default

1. Any tool tagged as a write action (e.g. tools that create branches, commits, PRs, or trigger workflows) should be considered **dangerous** and only used intentionally.
2. Do **not** merge or close PRs unless Joey explicitly tells you to:
   - `merge_pull_request`
   - `close_pull_request`
3. When creating PRs:
   - Use a clear, descriptive title.
   - Provide a concise body explaining what was changed and why.
4. Do not delete branches via shell commands or GitHub APIs unless Joey explicitly requests it.

---

## 7. Handle errors explicitly

1. For `apply_patch_and_open_pr`, always inspect the `error` field:
   - `git_apply_failed` – patch did not apply; usually due to stale contents or incorrect hunks.
   - `git_commit_failed` – commit step failed; check `stderr` for details.
   - `tests_failed` – tests failed; include the failure summary in your response.
   - `git_push_failed` – push failed; often branch protection, auth, or network issues.
2. If `git_apply_failed`:
   1. Fetch the latest contents again.
   2. Rebuild a smaller, more targeted patch.
3. If tests fail:
   - Do not try to “fix” everything automatically in a single step.
   - Summarize the failures and propose next steps; wait for Joey’s direction.
4. Do not repeatedly retry a failing write operation without explaining the problem and getting confirmation.

---

## 8. Use `run_tests` and `run_command` deliberately

1. `run_tests` and `run_command` clone the repository into a temporary directory and run shell commands.
2. These tools can be slow and resource-intensive; use them when they add real value (e.g. running pytest, flake8, or a specific script).
3. Typical patterns:
   - `run_tests(..., test_command="pytest")` – run the test suite.
   - `run_tests(..., test_command="flake8 .")` – run style checks.
4. Do not build complex shell pipelines; prefer a single well-scoped command per call.

---

## 9. Respect Joey’s preferences and limits

1. Keep changes small and reviewable; prefer multiple small PRs over one huge PR.
2. Avoid touching unrelated files in the same patch/PR.
3. When generating documentation, split very long content into clearly named parts (e.g. `PART_1`, `PART_2`) if necessary.
4. When in doubt, explain what you intend to do (which tool, with which key arguments) before doing it.

---

## 10. When you are unsure

1. If you are unsure whether an action is safe or how a tool behaves:
   - Explain your understanding of the tool.
   - Propose a minimal, low-risk action.
   - Ask Joey to confirm before performing large or irreversible changes.
2. Always favor clarity and safety over cleverness or automation.
