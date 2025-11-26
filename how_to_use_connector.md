# How to Use Joey’s GitHub MCP Connector in This Repository

This repository is managed through **Joey’s GitHub MCP server** (the “Joey’s GitHub” connector in ChatGPT / MCP-aware tools).  
Any assistant working in this repo MUST follow the rules in this document when reading, editing, testing, or otherwise interacting with the code.

---

## 1. Connector to use (and what NOT to use)

1. Always use the **Joey’s GitHub MCP server** to interact with this repository.
2. Do **not** use:
   - Built-in / generic GitHub connectors.
   - Ad-hoc HTTP requests to the GitHub API.
   - Manual copy-paste workflows when a proper MCP tool exists.
3. All Git operations (branches, commits, PRs, tests, workflows) must go through the Joey’s GitHub MCP tools.

If you are unsure which connector is Joey’s GitHub:  
It is the one explicitly described as a **GitHub MCP server** or named something like **“Joeys GitHub”**.

---

## 2. Golden rules

These are non-negotiable.

1. **Read before you write**
   - Always fetch the current file contents from Joey’s GitHub before editing.
   - Use:
     - `get_file_contents` for a single file.
     - `fetch_files` for multiple files.
   - Both file tools return `numbered_lines`, so cite exact line numbers when
     planning patches.
   - Never guess what is on `main` or any branch; always base edits on live data.

2. **Use unified diffs for code changes**
   - For code, the default workflow is:
     1. Fetch current content with Joey’s GitHub tools.
     2. Compute the exact edits.
     3. Generate a **unified diff** (like `git diff` output).
     4. Call `apply_patch_and_open_pr` with that diff.
   - Do **not** replace entire files with new content unless explicitly instructed by Joey.

3. **Keep changes small and focused**
   - Each patch should be:
     - Roughly ≤ 500 lines, and
     - Roughly ≤ 20k characters.
   - If you need larger changes, break them into multiple patches / PRs.

4. **Use `content_url` by default only for docs**
   - For medium/large docs: write the content to the sandbox (`/mnt/data/...`) and then use `content_url` with:
     - `commit_file_async`, or
     - `update_files_and_open_pr`.
   - For code: prefer unified diffs with `apply_patch_and_open_pr`. Only use `content_url` for code if Joey explicitly asks.

5. **Avoid huge inline payloads**
   - Do not send enormous strings in `content` parameters.
   - Prefer:
     - Patches (diffs) for code.
     - Sandbox + `content_url` for larger docs.
   - Small inline strings (short snippets, tiny docs) are acceptable.

6. **Treat all write tools as dangerous by default**
   - Any tool that can modify GitHub state (branches, commits, PRs, workflows) must be used deliberately.
   - Never call a write tool “just to see what happens.”

7. **Always check errors and return values**
   - After any write or test tool, inspect the result:
     - Look for `error`, `exit_code`, `timed_out`, `stderr`, and status fields.
     - Never assume success without checking.

---

## 3. Core tools and patterns

You do not need to memorize every argument; you MUST follow the patterns.

### 3.1 Read-only tools

Use these before any change:

- `get_repository(full_name)`  
- `list_branches(full_name, per_page, page)`  
- `get_file_contents(full_name, path, ref)`  
- `fetch_files(full_name, paths, ref)`  
- `graphql_query(query, variables)`  
- `fetch_url(url)`

Typical patterns:

- Inspect this repo:
  - `get_repository("owner/repo")`
- Read a single file on `main`:
  - `get_file_contents("owner/repo", "path/to/file.py", "main")`
- Read multiple files:
  - `fetch_files("owner/repo", ["file1.py", "dir/file2.py"], "main")`

Always use these tools to obtain fresh content before editing.

---

### 3.2 Code changes – patch workflow

For any code edit (bug fix, refactor, new feature):

1. **Fetch** the current file(s) via Joey’s GitHub.
2. **Plan and compute** the desired edits.
3. **Generate a unified diff**, for example:

   ```diff
   diff --git a/app/example.py b/app/example.py
   index abc1234..def5678 100644
   --- a/app/example.py
   +++ b/app/example.py
   @@ -10,6 +10,9 @@ def do_something(x):
        ...
   +    # New behavior
   +    if condition:
   +        handle_condition()
        return result


Apply via PR using apply_patch_and_open_pr:

Conceptual arguments:

full_name: "owner/repo"

base_branch: "main"

patch: unified diff string

title: short description

body: explanation of the change

new_branch: e.g. ally/<short-name>

run_tests_flag: true or false depending on context

test_command: usually "pytest"

Inspect the result:

If error is null → patch applied, branch pushed, PR opened.

If error is something like:

git_apply_failed

git_commit_failed

tests_failed

git_push_failed
then read the stderr field and respond accordingly.

Important rule:
If git_apply_failed occurs, you MUST:

Fetch the latest file contents again.

Rebuild a smaller or corrected patch.

Try again once, not in an infinite loop.

3.3 Docs and larger text content

Use different strategies for documentation versus code.

Small docs or small edits

Example: fix wording, add a short section.

Use the same patch workflow as code:

Fetch the doc.

Generate a unified diff.

Call apply_patch_and_open_pr.

New or larger docs

Example: long guides, part-based docs, handoff docs.

Use sandbox + content_url:

Write the doc in the sandbox, e.g. /mnt/data/how_to_use_connector.md.

Call update_files_and_open_pr or commit_file_async with content_url set to the sandbox path.

The host will rewrite the sandbox path into an internal HTTP(S) URL that Joey’s GitHub server can fetch.

Keep individual docs reasonably sized; split huge documents into multiple .md files if needed.

3.4 Tests, linting, and commands

The connector provides tools that clone the repo and run commands in a temporary working directory:

run_tests(full_name, ref, test_command, timeout_seconds, workdir, patch)

run_command(full_name, ref, command, timeout_seconds, workdir, patch)

Typical usage:

Run the pytest suite:

run_tests(
  full_name="owner/repo",
  ref="main" or "some-branch",
  test_command="pytest",
  timeout_seconds=600,
  patch="<your diff>"  # optional; apply local changes before running
)


Run flake8:

run_tests(
  full_name="owner/repo",
  ref="main",
  test_command="flake8 .",
  timeout_seconds=600,
  patch="<your diff>"  # optional; apply local changes before running
)


Rules:

Use these tools when they add real value (e.g. verifying tests/lint on a branch).

Do not construct complex shell pipelines; prefer a single clear command per call.

Always inspect:

exit_code

timed_out

stdout

stderr

If exit_code != 0, explain the failure and do not suppress the output.

3.5 PR and branch operations

The connector includes helpers such as:

list_pull_requests

create_pull_request

merge_pull_request (write, dangerous)

close_pull_request (write, dangerous)

comment_on_pull_request

create_branch

ensure_branch

compare_refs

Rules:

Do not merge or close PRs unless Joey explicitly asks you to.

When opening a PR:

Use a clear, descriptive title.

Provide a concise but informative body explaining what changed and why.

Avoid creating noisy or unused branches.

Only delete branches when Joey explicitly requests it.

4. Error-handling rules

When any tool fails, you MUST:

Never ignore errors

Inspect fields like:

error

status_code

exit_code

stderr

Surface these in your response.

Common cases

git_apply_failed (from apply_patch_and_open_pr):

Patch fails to apply.

Usually caused by stale contents or incorrect context.

Response:

Fetch latest contents.

Build a smaller or corrected patch.

Try once more.

empty_patch or empty_diff (from apply_patch_and_open_pr):

Patch body was empty/whitespace or applied cleanly but produced no staged
changes.

Response:

Rebuild the diff to include the intended edits.

Confirm the hunks actually change files; identical old/new lines return
`empty_diff` even when the patch text is non-empty.

tests_failed:

Tests ran but did not pass.

Response:

Summarize which tests failed and the key errors.

Do not auto-edit large parts of the repo blindly.

Propose specific next steps and wait for instructions.

git_push_failed:

Could be branch protection, auth, or network issues.

Response:

Surface full message from stderr or the API.

Do not keep retrying the same write operation without change.

No brute-force retries

If something fails more than once, stop, explain the failure, and ask Joey how to proceed.

5. Things you MUST NOT do

Do not:

Use a different GitHub connector for this repo when Joey’s GitHub is available.

Push changes via custom shell commands outside of the documented tools.

Replace large files without diffing, unless Joey explicitly requests a full rewrite.

Do not:

Merge or close PRs without Joey’s explicit approval.

Delete branches unless Joey explicitly requests it.

Run destructive commands in run_command (e.g. rm -rf, force pushes, etc.).

Do not:

Ignore test failures, linters, or tool errors.

Retry failing write operations repeatedly without a clear new plan.
