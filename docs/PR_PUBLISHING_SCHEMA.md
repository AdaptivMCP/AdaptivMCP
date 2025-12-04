# Pull Request Publishing Schema for Joey's GitHub Connector

This document defines the **canonical workflow and schema** every assistant must follow when creating PRs using the **Joey's GitHub** MCP server.

The goal is:

1. Consistent, predictable PRs that Joey can trust.
2. Minimal surprises or breakages across Joey's repos.
3. Clear traceability from assistant reasoning → diffs → tests → PR metadata.

This doc assumes:

- You are using the **Joey's GitHub MCP server**, not the built-in GitHub connector.
- The target repo is accessible via `Proofgate-Revocations/...` or other repos Joey owns.
- You treat `main` as protected: everything goes through PRs.

---

## 1. Pre-flight: understand the server and repo

Before making any changes, assistants must:

1. Call `get_server_config`.
   - Purpose: understand server settings and whether writes are allowed.
   - Read at least: `write_allowed`, timeouts, concurrency limits, sandbox flags.
   - If `write_allowed` is false, do not attempt write tools until Joey explicitly approves enabling writes.

2. Call `list_all_actions(include_parameters=true)` and `list_write_tools`.
   - Purpose: discover what write tools are available and how they are intended to be used.
   - Use this to confirm which tools exist and which are considered high-level vs low-level.

3. Confirm repo metadata.
   - Use `get_repository` (or equivalent) to confirm the default branch (usually `main`).
   - Use branch/PR tools to see what branches and open PRs already exist to avoid collisions.

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

These are the standard flows assistants should follow. They align with the branch-and-PR oriented, `run_command`-heavy workflows in `docs/WORKFLOWS.md`.

### 3.1 Flow A: small single-file change

Use this when you are editing one file and the change is modest in size.

1. Read the file with `get_file_contents(full_name, path, ref=<default_branch>)`.
2. Explain to Joey what you will change in plain language.
3. Prepare the full updated file content.
4. Use branch + commit tools, for example:
   - `ensure_branch` from `main`.
   - `run_command` in the workspace to edit and validate.
   - `commit_workspace` to commit and push.
   - A PR tool to open the pull request.
5. Confirm the PR response contains the branch and pull request details.
6. Report the PR link, summary of changes, and test status to Joey.

### 3.2 Flow B: multi-file change

Use this when you are editing multiple files as part of one logical change.

1. Read all affected files (via `fetch_files` or repeated `get_file_contents`).
2. Plan per-file changes in bullets and share with Joey.
3. Apply changes in the workspace via `run_command`.
4. Use `commit_workspace` on a feature branch to commit and push.
5. Open a PR and ensure the PR body follows the schema below.
6. Split changes into multiple PRs if the change is too large or touches unrelated concerns.

### 3.3 Flow C: new document from a stub

Use this when Joey has created a blank file or minimal stub and you want to fill in the content.

1. Confirm the stub exists with `get_file_contents` or `fetch_files`.
2. Draft the full document content in the conversation and get Joey's approval.
3. Apply the content via `run_command` in the workspace.
4. Commit with `commit_workspace` on a feature branch.
5. Open a PR; in the PR body, clearly state that this is a new document from a stub and explain how assistants should use it.

### 3.4 Flow D: running tests

Use `run_tests` or `run_command` when you changed code or tests and need to validate the suite.

1. Decide whether to run tests before or after opening the PR, based on Joey's guidance.
2. Use `run_tests` or `run_command` with the relevant command so the run matches the changes you are committing.
3. Inspect the command result for exit code and output.
4. If tests fail, include failure details in your report and ask Joey how to proceed.

---

## 4. Machine-friendly PR body schema

Assistants should internally construct a JSON object matching this schema, then render it into a Markdown PR body.

### 4.1 JSON shape

```jsonc
{
  "title": "Short PR title, ideally matching the GitHub PR title",
  "summary": [
    "Short bullet 1 describing the overall change",
    "Short bullet 2",
    "..."
  ],
  "motivation": "Why this change exists. Reference Joey's request or the underlying problem.",
  "context": "Optional extra context, links, or background.",
  "changes": [
    {
      "path": "docs/WORKFLOWS.md",
      "kind": "docs",          // one of: "code", "docs", "tests", "config", "meta"
      "summary": "Updated workflows to emphasize run_command usage.",
      "details": [
        "Clarified discovery/bootstrapping sequence.",
        "Added explicit reference to SELF_HOSTING_DOCKER.md.",
        "Tightened troubleshooting section."
      ]
    },
    {
      "path": "Dockerfile",
      "kind": "config",
      "summary": "Fix Docker RUN line so apt-get arguments are correct.",
      "details": [
        "Replaced stray literal \\\n characters with proper line continuations.",
        "Ensured image builds cleanly on Docker Desktop."
      ]
    }
  ],
  "testing": {
    "status": "passed",        // "not_run" | "passed" | "failed" | "not_applicable"
    "commands": [
      "pytest",
      "python -m compileall ."
    ],
    "details": "pytest passed locally; no additional tests needed for docs-only changes."
  },
  "risks": [
    "Low: docs-only changes.",
    "Config risk if Dockerfile change is incorrect; mitigated by local build."
  ],
  "rollback_plan": "Revert this PR in GitHub if any issues arise.",
  "follow_ups": [
    "Add CI job to validate Docker build.",
    "Extend tests for new workspace behavior."
  ],
  "breaking_changes": false,
  "linked_issues": [
    "#245",
    "chore: align docs with Docker self-hosting"
  ],
  "extra_notes": "Anything Joey should know that does not fit elsewhere."
}
```

Guidelines:

- `title` should usually match the GitHub PR title or be a close variant.
- `summary` should be 2–4 bullets, focused on behaviour and user impact.
- `changes` should group changes by file; keep `details` focused and concrete.
- `testing.status` must honestly reflect what happened; do not mark `passed` if tests were not run.
- `risks` and `rollback_plan` can be short, but they must be realistic.
- `follow_ups` is optional; omit or use an empty array if there is nothing to follow up on.
- `linked_issues` can include GitHub issue numbers or short labels if there is no formal issue.

### 4.2 Rendering to Markdown

When actually opening a PR, assistants should render the JSON schema into a Markdown body with this structure:

```md
## Summary

- <summary[0]>
- <summary[1]>
- ...

## Motivation / Context

<motivation>

<optional context section if `context` is non-empty>

## Changes by file

- `path/to/file.ext`
  - <changes[i].summary>
  - <each item in changes[i].details as a sub-bullet>

## Implementation notes (optional)

Use this section for any design decisions, trade-offs, or constraints that Joey should know about.

## Testing

- Status: **<testing.status>**
- Commands:
  - `<testing.commands[0]>`
  - `<testing.commands[1]>`
- Details: <testing.details>

## Risks and rollback

- Risks:
  - <risks[0]>
  - <risks[1]>
- Rollback plan: <rollback_plan>

## Follow-ups (optional)

- <follow_ups[0]>
- <follow_ups[1]>

## Linked issues / references

- <linked_issues[0]>
- <linked_issues[1]>

## Extra notes

<extra_notes>
```

Assistants should keep the Markdown body stable and predictable so Joey quickly recognizes the sections.

---

## 5. Error handling and guardrails

When using write tools and publishing PRs, assistants must:

1. Handle empty edits

- If your update would produce no effective change, do not open a PR.
- Explain to Joey that the repo already matches the desired state.

2. Handle content drift

- Common causes: file content on `main` changed since you fetched it.
- Recovery steps:
  1. Re-fetch the current version of the affected files.
  2. Rebuild the updated content from the latest version.
  3. Retry the commit/PR once.
  4. If it still fails, stop and describe the failure rather than brute-forcing.

3. Handle tool errors clearly

- If a tool call fails (schema error, validation error, or API error):
  - Quote the relevant part of the error message.
  - Re-check the tool schema via `list_all_actions(include_parameters=true)`.
  - Fix the payload instead of retrying blindly.

4. Respect write gating

- If writes are disabled or `authorize_write_actions` is not approved, do not try to sneak in writes via other tools.
- Always tell Joey when you are about to perform write actions and confirm that this matches their expectations.

5. Provide a clear end-of-work summary

At the end of a workflow that results in a PR:

- Restate the branch name and PR link.
- Summarize what changed and which files were touched.
- Summarize tests and their outcomes.
- Call out any risks, follow-ups, or places where you deliberately left things for Joey to decide.

This schema is meant to be rich enough that assistants can follow it mechanically while still staying readable for a solo developer reviewing PRs quickly.
