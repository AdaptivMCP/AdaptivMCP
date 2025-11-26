# Pull Request Schema for Assistants

This document defines the standard pull request (PR) schema that all assistants
must follow when working in this repository using Joey's GitHub MCP.

The aims are to make every PR easy to review, easy to extend, and traceable back
to the prompts and decisions that produced it.

---

## 1. Branch naming

Every assistant-created branch should follow this pattern:

```text
ally/<short-purpose>-<sequence>
```

Examples:

- ally/add-pr-schema-1
- ally/docs-cleanup-2
- ally/fix-fetch-files-3

Rules:

1. Always start with ally/.
2. Use a short, kebab-case description of the change.
3. Optionally add a small sequence number if there will be several related
   branches.
4. Do not reuse a branch name once it has been merged or closed.

When calling apply_patch_and_open_pr, set:

- base_branch to main (unless Joey explicitly asks for something else).
- new_branch to a value following the pattern above.

---

## 2. PR title schema

PR titles must be short, descriptive, and follow this format:

```text
[area] Short, action-style summary
```

Where [area] is one of these tags (or a combination of two):

- [docs]    documentation changes only
- [infra]   Render config, environment variables, CI, infrastructure
- [tools]   MCP tools, helpers, workflows
- [tests]   new or updated tests only
- [bugfix]  fixes a specific bug in behaviour
- [refactor] internal code cleanup without behaviour change

Examples:

- [docs] Add PR schema guide for assistants
- [tools] Harden apply_patch_and_open_pr error handling
- [tests] Add smoke test for run_tests helper

---

## 3. PR body schema

The PR body must follow this ordered template. Use headings exactly as shown.

### Summary

One to three sentences describing what the PR does and why.

### Changes

Bullet list of concrete changes, grouped by area if helpful. For example:

- Docs
  - Added PR_SCHEMA.md describing the PR workflow for assistants.
- Code
  - Updated a helper in main.py to improve error handling.

If the PR only touches documentation, say so explicitly.

### Implementation notes (for assistants)

Short section aimed at future assistants. Include:

- Non-obvious design decisions.
- Limitations or trade-offs you are aware of.
- How this change interacts with existing tools or documents.

### Testing

Summarise what testing was performed. Use one of these patterns:

- Tests: not run (docs-only change)
- Tests: run via run_tests with command `pytest`
- Tests: run via run_tests with command `pytest -k <pattern>`
- Tests: run via run_tests with command `flake8 .`

If tests failed and the PR is still opened to get help, describe:

- Which tests failed.
- The key error messages.
- Any hypotheses about the cause.

### Risks and rollout

Provide a brief risk assessment and any post-merge steps. For example:

- Risk: low – docs-only change.
- Risk: medium – changes behaviour of GitHub API error handling.
- Risk: high – affects commit or PR workflows and should be merged when Joey
  is available to intervene if needed.

If Joey must take manual actions after merge (redeploy on Render, rotate
tokens, change environment variables), list them here.

---

## 4. Expectations for assistants per PR

When you use apply_patch_and_open_pr (or another helper that opens a PR) you
must:

1. Fetch latest state before building your patch. Use get_file_contents or
   fetch_files against the branch you intend to modify.
2. Keep the patch small and focused. Stay under roughly 500 changed lines and
   20k characters per patch. Split large efforts into several PRs.
3. Populate the PR body using the schema above, in the exact order of
   sections.
4. Inspect the tool result carefully. If the error field is not null, do not
   assume the PR exists; surface the error to Joey instead.
5. Avoid noisy follow-up PRs. If you find a small issue immediately after
   opening a PR, prefer an extra commit on the same branch over a second PR.

---

## 5. Example PR body skeleton

```markdown
Summary

Short paragraph explaining what this PR does and why.

Changes
