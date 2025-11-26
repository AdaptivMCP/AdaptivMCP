# USAGE_EXAMPLES.md

Practical examples for using Joey's GitHub MCP connector against this repository
and others configured the same way.

These examples are written for assistants and tools that can call Joey's GitHub
MCP methods (such as ChatGPT with the Joey's GitHub connector enabled). They
assume you already know the repository full name, for example:

- `Proofgate-Revocations/chatgpt-mcp-github`

Throughout, replace `FULL_NAME` with the appropriate `owner/repo` string.

---

## 1. Read-only inspection

### 1.1 Inspect repository and branches

Use these patterns when you want to understand the shape of a repo before
changing anything:

- Repository metadata:

  - `get_repository("FULL_NAME")`

- Branches:

  - `list_branches("FULL_NAME", per_page=100, page=1)`

### 1.2 Read files with line numbers

To plan edits, always fetch live file content with line numbers:

- Single file on `main`:

  - `get_file_contents("FULL_NAME", "tests/test_smoke.py", "main")`

- Multiple files at once:

  - `fetch_files("FULL_NAME", ["main.py", "README.md"], "main")`

Both tools return `numbered_lines` so you can reference specific lines when
describing patches.

### 1.3 Browse the repository tree

When you are unsure where a file lives, list the repository structure quickly:

- Entire tree on `main` (truncated to 1000 entries by default):

  - `list_repository_tree("FULL_NAME", ref="main")`

- Zoom into a folder to avoid truncation and keep the response fast:

  - `list_repository_tree("FULL_NAME", ref="main", path_prefix="tests/")`

The response includes `entry_count`, `truncated`, and `entries` with the path
and type for each item. If `truncated` is `true`, reduce `path_prefix` or lower
`max_entries` and call again to navigate progressively without getting lost.

---

## 2. Code change via unified diff + tests

This is the primary pattern for code changes: small, focused diffs applied via
`apply_patch_and_open_pr` with tests.

### 2.1 Example – add a new smoke test

Goal: add a new test to `tests/test_smoke.py` that imports `main.py` and checks
that the FastMCP app exists.

1. Read the current file:

   - `get_file_contents("FULL_NAME", "tests/test_smoke.py", "main")`

2. Plan the change, for example adding:

   ```python
   def test_tools_available():
       """Ensure Joey's GitHub MCP tools are importable."""
       import importlib

       main = importlib.import_module("main")
       assert hasattr(main, "app")
   ```

3. Construct a unified diff (conceptually similar to what `git diff` would
   produce) that adds this block.

4. Apply the patch and run tests:

   - Tool: `apply_patch_and_open_pr`
   - Arguments (conceptual):

     - `full_name`: `"FULL_NAME"`
     - `base_branch`: `"main"`
     - `patch`: the unified diff string
     - `title`: `"Add MCP tools import smoke test"`
     - `body`: brief explanation of the change
     - `new_branch`: e.g. `"ally/test-mcp-smoke-tools"`
     - `run_tests_flag`: `true`
     - `test_command`: `"pytest"`
     - `test_timeout_seconds`: `600`
     - `draft`: `false`

5. Inspect the result:

   - Confirm `error` is `null`.
   - Check `tests.exit_code == 0` and review `tests.stdout` for pytest output.
   - Use the returned PR metadata to report the branch and PR number to Joey.

This is exactly the pattern used to create PR **#73** in this repository.

---

## 3. Creating a brand new documentation file

You can create an entire new file from scratch using a unified diff that turns
`/dev/null` into a concrete path.

### 3.1 Example – add `TROUBLESHOOTING.md`

Goal: create a new troubleshooting guide documenting common Render and MCP
issues.

1. Draft the full markdown content for `TROUBLESHOOTING.md`.

2. Build a unified diff that creates the file, conceptually like:

   ```diff
   diff --git a/TROUBLESHOOTING.md b/TROUBLESHOOTING.md
   new file mode 100644
   --- /dev/null
   +++ b/TROUBLESHOOTING.md
   @@ -0,0 +1,5 @@
   +# TROUBLESHOOTING.md
   +...
   ```

3. Call `apply_patch_and_open_pr` with that diff and `run_tests_flag=true`.

4. Verify:

   - Tests pass.
   - A new PR was opened on a branch like `"ally/add-troubleshooting-doc"`.

This is the pattern that created PR **#74** and the `TROUBLESHOOTING.md` file in
this repo.

---

## 4. Documentation edits

For small and medium documentation changes, treat docs like code and use diffs.

### 4.1 Example – update `how_to_use_connector.md`

1. Fetch the file:

   - `get_file_contents("FULL_NAME", "how_to_use_connector.md", "main")`

2. Plan a small, focused change (for example, adding a new rule or clarifying a
   section).

3. Construct a unified diff with the minimal necessary edits.

4. Apply it via `apply_patch_and_open_pr` (tests are still useful, but may not
   be strictly required for doc-only changes).

5. Link the resulting PR back to Joey for review and merge.

For very large new docs, you can instead write the content to a sandbox path and
use `content_url` with `update_files_and_open_pr` or `commit_file_async`, as
described in `how_to_use_connector.md`.

---

## 5. Running tests and linting

### 5.1 Run pytest on a branch

To verify a branch passes tests:

- Tool: `run_tests`
- Example arguments:

  - `full_name`: `"FULL_NAME"`
  - `ref`: `"some-feature-branch"`
  - `test_command`: `"pytest"`
  - `timeout_seconds`: `600`

Inspect the result:

- `exit_code`: `0` indicates success.
- `stdout`: collected pytest output.
- `stderr`: any errors; do not ignore if present.

### 5.2 Run flake8 (or other linters)

You can use `run_tests` (or `run_command`) for linters as well:

- `test_command`: `"flake8 ."`
- `patch`: optional unified diff to apply before running (lets you lint the
  in-progress changes you generated locally)

Same rules apply: inspect `exit_code`, `stdout`, and `stderr`, and summarize
any failures instead of hiding them.

---

## 6. GitHub Actions workflows

### 6.1 Inspect and trigger workflows

Use the Actions-related tools to integrate CI/CD into your workflow:

- List recent runs:

  - `list_workflow_runs("FULL_NAME", branch="main", status="completed")`

- Trigger a workflow:

  - `trigger_workflow_dispatch("FULL_NAME", "ci.yml", "main", inputs={...})`

- Trigger and wait for completion:

  - `trigger_and_wait_for_workflow("FULL_NAME", "ci.yml", "main", inputs={...},
    timeout_seconds=900, poll_interval_seconds=10)`

Always treat these as write operations and use them only when there is a clear,
documented reason to run CI/CD from the connector.

---

## 7. Branch and PR hygiene

### 7.1 Creating feature branches

Use the branch helpers when you need reusable branches:

- `create_branch("FULL_NAME", "ally/feature-name", from_ref="main")`
- `ensure_branch("FULL_NAME", "ally/feature-name", from_ref="main")`

### 7.2 Opening PRs directly

If you already have a branch pushed (for example, created by `apply_patch_and_open_pr`):

- `create_pull_request("FULL_NAME", title, head="ally/feature-name", base="main", body=...)`

### 7.3 Things to avoid

- Do not merge or close PRs unless Joey explicitly requests it.
- Do not delete branches unless Joey explicitly requests it.
- Do not run destructive shell commands via `run_command` (e.g. `rm -rf`,
  force pushes).

---

## 8. Advanced: content_url for large docs

For situations where a document is too large for a single patch or needs to be
generated in a different environment, you can use `content_url` with:

- `commit_file_async`
- `update_files_and_open_pr`

High-level pattern:

1. Generate the document and host it at a stable `https://` URL that Joey's
   server can fetch.
2. Call `commit_file_async` or `update_files_and_open_pr` with `content_url`
   pointing at that URL.

Use this only when patch-based workflows are not practical, and prefer unified
diffs for all normal code and doc work in this repository.
