# CONNECTOR_DOCS_OVERVIEW.md

Master index and end-to-end usage patterns for Joey's GitHub MCP connector.

This document ties together all the other docs in this repo and defines the
exact flows assistants should follow to reach final results:

- Small, focused code changes.
- New docs created via diffs.
- Tests and linting.
- GitHub Actions workflows.
- Rich, structured PRs.

It also defines the doc stack so assistants always know where to look.

---

## 1. Documentation map

Use this as the route map for all connector-related docs.

- **`README.md`**
  - What it covers:
    - High-level description of the GitHub MCP server.
    - Render deployment details (endpoint, `/sse`, `/healthz`).
    - Required environment variables (GitHub token, HTTP settings, concurrency).
  - When to read:
    - When debugging deployment or Render environment issues.
    - When someone new asks "what is this service and how is it hosted?"

- **`README_connector.md`**
  - What it covers:
    - MCP connector surface from the client’s point of view.
    - Server name, endpoint URL, and how to configure the MCP connector in a
      client like ChatGPT.
    - Overview of tools exposed (read-only, write, workflows, workspace tools).
  - When to read:
    - When configuring or verifying the MCP connector in a client.
    - When you need a high-level tool inventory.

- **`how_to_use_connector.md`**
  - What it covers:
    - Hard rules for assistants working **inside this repo**.
    - Use Joey’s GitHub MCP only (no generic GitHub connector).
    - "Read before write" behavior and size limits for patches.
    - Primary workflow: unified diffs + `apply_patch_and_open_pr`.
    - When and how to use `content_url` (advanced, docs-first).
  - When to read:
    - Before making **any** change in this repo.
    - When deciding whether to use `apply_patch_and_open_pr` vs. other tools.

- **`how_to_use_connector_ceo.md`**
  - What it covers:
    - High-level mental model of the connector for Joey.
    - What you can expect assistants to do for you.
    - Where environment variables and PAT live.
  - When to read:
    - When you want to sanity-check how assistants should be using the system.

- **`USAGE_EXAMPLES.md`**
  - What it covers:
    - Practical, worked examples of:
      - Read-only inspection (`get_repository`, `list_branches`,
        `get_file_contents`, `fetch_files` with `numbered_lines`).
      - Code change via unified diff + `apply_patch_and_open_pr` + tests
        (like the additional MCP smoke test).
      - Creating new docs via diffs (like `TROUBLESHOOTING.md`).
      - Tests and lint (`run_tests` / `run_command`).
      - Branch + PR hygiene and workflows.
  - When to read:
    - When you want concrete, copyable patterns for a specific type of change.

- **`MCP_ERROR_CODES.md`**
  - What it covers:
    - Common MCP / GitHub / Render failure modes and error patterns.
    - How to interpret `error` fields, HTTP status codes, and when to escalate.
  - When to read:
    - Immediately after any tool call fails or returns an unexpected error.
    - When deciding whether a failure is likely in code, configuration, or
      external infrastructure.

- **`TROUBLESHOOTING.md`**
  - What it covers:
    - Typical failure modes and their fixes:
      - Render import errors in `main.py`.
      - Write gate / `WriteNotAuthorizedError`.
      - `git_apply_failed`, `tests_failed`, `git_push_failed`.
      - GitHub rate limiting.
      - MCP connector misconfiguration.
  - When to read:
    - When a tool call fails or Render deploy breaks.
    - When you see specific error codes and need the "known fix."

- **`PR_SCHEMA_GUIDE.md`**
  - What it covers:
    - Standardized schema for:
      - Branch names.
      - PR titles.
      - PR body sections (Summary, Motivation/Context, Changes, Testing,
        Risk/Impact, MCP/Tooling Details, Checklist).
    - Examples of well-formed PR bodies (docs-only, tests-only).
    - Assistant obligations per session.
  - When to read:
    - Every time an assistant creates a PR.
    - When reviewing whether a PR body is "up to spec."

---

## 2. Core scenarios and which tools/docs to use

This section maps real workflows to the tools and docs.

### 2.1 Small code change with tests (primary scenario)

**Goal:** Change behavior in code (e.g. add a test, tweak logic, small refactor).

**Docs to consult:**

1. `how_to_use_connector.md` – rules of engagement.
2. `USAGE_EXAMPLES.md` – section on code changes via unified diff.
3. `PR_SCHEMA_GUIDE.md` – PR title/body and branch naming.

**Tool flow:**

1. Read the relevant files:

   - `get_file_contents("FULL_NAME", "<path>.py", "main")`
   - Use `numbered_lines` to reference exact lines.

2. Plan a small, focused change (≤ ~500 lines / ~20k chars).

3. Construct a unified diff:

   - Use the current file content as the `a/` side.
   - New version as the `b/` side.
   - Ensure the context lines match exactly.

4. Call:

   - `apply_patch_and_open_pr` with:
     - `full_name`: `"FULL_NAME"`
     - `base_branch`: `"main"`
     - `patch`: unified diff string.
     - `title`: per `PR_SCHEMA_GUIDE.md`.
     - `body`: using the PR template sections.
     - `new_branch`: `ally/<short-kebab>`.
     - `run_tests_flag`: `true`.
     - `test_command`: `"pytest"`.
     - `test_timeout_seconds`: `600`.

5. Inspect result:

   - `error` is `null`.
   - `tests.exit_code == 0`, `tests.stdout` shows passing pytest.
   - PR metadata includes PR number and URL.

**Result:** A reviewable code change with tests, in a PR that matches the schema.

---

### 2.2 New documentation file via diff (we’ve already done this)

**Goal:** Add a brand new doc (e.g. `TROUBLESHOOTING.md`, `USAGE_EXAMPLES.md`,
`PR_SCHEMA_GUIDE.md`).

**Docs to consult:**

1. `USAGE_EXAMPLES.md` – new doc example.
2. `PR_SCHEMA_GUIDE.md` – PR structure.

**Tool flow:**

1. Draft full doc content in the assistant’s workspace (small enough to fit in a
   single patch).

2. Build a unified diff that creates the file:

   ```diff
   diff --git a/NEW_DOC.md b/NEW_DOC.md
   new file mode 100644
   --- /dev/null
   +++ b/NEW_DOC.md
   @@ -0,0 +N @@
   +# NEW_DOC.md
   +...
   ```

3. Use `apply_patch_and_open_pr` with `run_tests_flag=true`:

   - Tests validate that the codebase is still good after adding docs.

4. PR body:

   - Use `## Summary` to describe doc purpose.
   - State in `## Changes` that it’s docs-only.
   - In `## Testing`, either:
     - Say `pytest` was run and passed, *or*
     - Explicitly state no tests were run (for purely docs-only repos).

---

### 2.3 Editing existing docs

**Goal:** Adjust or extend existing docs (e.g. `how_to_use_connector.md`,
`README_connector.md`).

**Docs to consult:**

- `how_to_use_connector.md` – rules.
- `USAGE_EXAMPLES.md` – doc edit example.
- `PR_SCHEMA_GUIDE.md` – PR shape.

**Tool flow:**

1. Fetch the doc:

   - `get_file_contents("FULL_NAME", "how_to_use_connector.md", "main")`

2. Plan a minimal, focused change.

3. Construct a unified diff with only the necessary hunks.

4. Apply via `apply_patch_and_open_pr`:

   - `run_tests_flag` can still be `true` – docs shouldn’t break tests.

5. Use the PR schema to describe what changed and why.

---

### 2.4 Test- or lint-only changes

