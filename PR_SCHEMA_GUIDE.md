# PR_SCHEMA_GUIDE.md

Standard schema and expectations for pull requests created via Joey's GitHub MCP
connector. Every assistant should follow this structure for **every PR body**
they create, regardless of repo, unless Joey explicitly overrides it.

This document is written for assistants and tools using the Joey's GitHub MCP
server (e.g. via `apply_patch_and_open_pr`, `update_files_and_open_pr`, or
`create_pull_request`).

---

## 1. Branch naming

All assistant-created branches MUST follow this pattern:

- Prefix with the assistant identity or role:
  - `ally/` for this assistant.
  - `codex/` or similar for other automation, if Joey defines it.
- Short, kebab-case description of the change.

Examples:

- `ally/add-troubleshooting-doc`
- `ally/fix-content-url-validation`
- `ally/update-how-to-use-connector`

Avoid:

- Very long branch names.
- Generic names like `patch-1`, `test`, `temp`.

---

## 2. PR title schema

PR titles MUST be:

1. Short (ideally ≤ 80 characters).
2. Action-oriented (what this change does).
3. Specific enough that Joey can distinguish PRs in the list.

Recommended patterns:

- `Add <thing>`
- `Fix <bug/issue>`
- `Refactor <area>`
- `Improve <behavior>`
- `Docs: <document or area>`
- `Tests: <suite or behavior>`

Examples:

- `Add TROUBLESHOOTING.md for Joey's GitHub MCP`
- `Docs: add USAGE_EXAMPLES.md usage guide`
- `Tests: add MCP tools import smoke test`
- `Refactor: simplify content_url validation`

Avoid:

- Titles like `Update files`, `Minor changes`, or `Fix stuff`.
- Including issue numbers only (e.g. `#123`). Use the body for linkage.

---

## 3. PR body schema (required sections)

Every PR body created by an assistant MUST follow this exact section structure,
in this order. Sections may be short, but they must be present.

### 3.1 Template

Assistants should treat the following as the canonical template and fill it in
for each PR. Fields with `(required)` MUST be filled. Fields with `(optional)`
can be omitted only if clearly not applicable.

```markdown
## Summary (required)

- One-line summary of the change.
- Optional second bullet for extra context.

## Motivation / Context (required)

- Why this change is being made.
- Link to any prior PRs, issues, or conversations if known.

## Changes (required)

- **Code:** Brief description of code-level changes (functions, modules, behavior).
- **Tests:** What tests were added/updated (or explicitly: "No tests; explain why").
- **Docs:** What documentation files were added/updated, if any.

## Testing (required)

- Command(s) run:
  - `pytest`
  - `pytest tests/test_smoke.py`
  - `flake8 .`
- Result:
  - `All tests passed`
  - Or list failing tests and errors if `run_tests`/`run_command` returned failures.

If no automated tests were run, state explicitly:
- `No automated tests run (explain why, e.g. doc-only change).`

## Risk / Impact (required)

- Risk level: `Low`, `Medium`, or `High`.
- What could break if this change is wrong.
- Any migration or rollout notes, if applicable.

## MCP / Tooling Details (required for assistant-created PRs)

- Tools used (for example):
  - `apply_patch_and_open_pr`
  - `run_tests` with `pytest`
- Branch name used.
- Any notable tool errors encountered and resolved.

## Checklist (required)

- [ ] Changes are small and focused (≤ ~500 lines / ~20k characters per patch).
- [ ] No secrets, tokens, or credentials are included in code or docs.
- [ ] Tests were run, or it is clearly explained why they were not.
- [ ] The title and summary accurately describe the change.
- [ ] This PR does not merge/close other PRs unless Joey explicitly requested it.
```

---

## 4. Examples of well-formed PR bodies

### 4.1 Example: new troubleshooting document

```markdown
## Summary (required)

- Add TROUBLESHOOTING.md documenting common Render and MCP issues.
- Helps assistants and Joey debug problems without re-discovering prior fixes.

## Motivation / Context (required)

- Joey wants a central place for render/MCP failure modes.
- This captures known issues (write gate, git_apply_failed, tests_failed, etc.)
  so future assistants can work from a stable baseline.

## Changes (required)

- **Code:** No code changes.
- **Tests:** No new tests; existing suite still used as validation.
- **Docs:** New file TROUBLESHOOTING.md added at repo root.

## Testing (required)

- Command(s) run:
  - `pytest`
- Result:
  - All tests passed (17 passed).

## Risk / Impact (required)

- Risk level: Low.
- This PR is documentation-only and does not affect runtime behavior.

## MCP / Tooling Details (required for assistant-created PRs)

- Tools used:
  - `apply_patch_and_open_pr` with a new-file diff.
  - `run_tests` (invoked by apply_patch_and_open_pr) using `pytest`.
- Branch name: `ally/add-troubleshooting-doc`.
- No tool errors encountered.

## Checklist (required)

- [x] Changes are small and focused (single new doc).
- [x] No secrets, tokens, or credentials included.
- [x] Tests were run (`pytest`) and passed.
- [x] Title and summary describe the change accurately.
- [x] This PR does not merge or close any other PRs.
```

### 4.2 Example: small test-only change

```markdown
## Summary (required)

- Add a smoke test that imports main.py and asserts that the MCP app exists.

## Motivation / Context (required)

- Ensure import-time errors in main.py are caught by pytest.
- Validates that FastMCP and the HTTP app can be created successfully.

## Changes (required)

- **Code:** Added `test_tools_available` in `tests/test_smoke.py`.
- **Tests:** Existing test suite extended with a simple import test.
- **Docs:** No documentation changes.

## Testing (required)

- Command(s) run:
  - `pytest`
- Result:
  - All tests passed (17 passed).

## Risk / Impact (required)

- Risk level: Low.
- Changes are limited to test suite only.

## MCP / Tooling Details (required for assistant-created PRs)

- Tools used:
  - `apply_patch_and_open_pr` with a unified diff against `tests/test_smoke.py`.
  - Tests run via `pytest` as part of the tool call.
- Branch name: `ally/test-mcp-smoke-tools`.
- No tool errors encountered.

## Checklist (required)

- [x] Changes are small and focused (single test function).
- [x] No secrets, tokens, or credentials included.
- [x] Tests were run and passed.
- [x] Title and summary describe the change accurately.
- [x] This PR does not merge or close any other PRs.
```

---

## 5. Assistant obligations each session

For every new MCP session where an assistant may create PRs in this repo (or
others following the same rules), the assistant MUST:

1. Use Joey's GitHub MCP connector, not a generic GitHub connector.
2. Confirm write access is enabled (via environment or `authorize_write_actions`).
3. Follow the **branch naming** rules in section 1.
4. Follow the **PR title** rules in section 2.
5. Use the **PR body template** in section 3 whenever they create a PR.
6. Keep patches small, targeted, and reviewable.
7. Surface all tool errors (including `git_apply_failed`, `tests_failed`,
   `git_push_failed`) in their explanation to Joey instead of hiding them.

If any of these rules conflict with a direct instruction from Joey, Joey's
explicit instruction wins, and the assistant should note the deviation in the
PR body under **MCP / Tooling Details**.
