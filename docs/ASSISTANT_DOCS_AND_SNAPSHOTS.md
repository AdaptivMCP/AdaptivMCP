# Assistant Docs and Snapshots

This document provides guidance for assistants (and advanced users) on how to keep documentation and mental models in sync with the actual behavior of the Adaptiv Controller GitHub MCP server.

The goal is to ensure that assistants:

- Rely on the **live tool surface** (via `get_server_config` and `list_all_actions`) as the source of truth.
- Keep written documentation up to date when tools, workflows, or safety rules change.
- Avoid stale assumptions and avoid hard-coding outdated behavior into prompts or snapshots.

---

## 1. Source of truth: live server, then docs

When reasoning about capabilities, assistants should prioritize:

1. **Live MCP server configuration**
   - Use `get_server_config` to understand what tools and settings are currently exposed.
   - Use `list_all_actions` to see the full list of MCP tools, their annotations, and their write/read status.

2. **Repository docs**
   - `README.md` for high-level product and architecture context.
   - `docs/WORKFLOWS.md` for recommended end-to-end flows.
   - `docs/ARCHITECTURE_AND_SAFETY.md` (once implemented) for deeper internals and guarantees.
   - `docs/SELF_HOSTED_SETUP.md` (once implemented) for deployment and operator guidance.

3. **Snapshots or controller prompts**
   - System prompts or saved snapshots in ChatGPT are helpful but can drift over time.
   - Treat them as a **starting point**, not as an immutable spec.

Whenever there is a conflict:

- Prefer the current branch code and docs in this repo over older snapshots.
- If something seems inconsistent, open or update a GitHub issue to clarify and then update the docs after the behavior is fixed.

---

## 2. Keeping docs in sync with code and tests

Assistants should treat documentation as first-class:

- When implementing new tools or changing behavior, ask: **"Do I also need to update docs/WORKFLOWS.md or related docs?"**
- Use the same branch and PR flow for docs as for code:
  - Create or update markdown files using `apply_text_update_and_commit` or patch-based flows.
  - Include docs changes in the same PR as the code change when they are tightly related.

Recommended practice:

1. **Before making changes**
   - Read the relevant docs sections and tests that describe the behavior.
   - Confirm that the planned change is consistent with the documented safety model and workflows.

2. **After making changes**
   - Review docs and tests again:
     - If tests were updated, make sure the docs mention any new constraints or behaviors.
     - If new tools were added, link them from the appropriate docs and README.

3. **When in doubt**
   - Open a docs-focused issue (or use existing ones like #128, #129, #130) and propose edits.
   - Explain in the issue or PR description why the doc change is needed.

---

## 3. Designing and evolving controller prompts

The Adaptiv Controller product is largely defined by how the ChatGPT controller prompt orchestrates these GitHub tools. Assistants should:

- Keep prompts **descriptive** rather than brittle.
- Refer to **behaviors and constraints** instead of spelling out every tool signature.
- Lean on the live tool list and docs instead of duplicating them in the prompt.

Example prompt guidelines:

- Emphasize safety model:
  - "Never write to main for the controller repo; always use feature branches."
  - "Use issue tools to keep humans informed of work and status."
  - "Use patch-based flows for code changes and always show diffs for approval."

- Reference docs by concept:
  - "Follow the branching and PR patterns described in the WORKFLOWS doc."
  - "When unsure about a tool, inspect list_all_actions and the relevant tests."

When tools or behaviors change:

- Update the controller prompt **after** the code and docs have been updated and merged.
- Clearly signal in the prompt (and possibly in a changelog) what version or commit of the controller it is aligned with.

---

## 4. Using issues to coordinate work

Issues are the backbone of human-assistant coordination in this repository. Assistants should:

- Use `create_issue` to capture new work, questions, or follow-ups.
- Use `update_issue` to keep the main description in sync with the current plan.
- Use `comment_on_issue` to log progress, design decisions, and links to PRs.

Suggested structure for issues:

- **Title**: concise but descriptive (for example "Docs: WORKFLOWS and ASSISTANT_DOCS_AND_SNAPSHOTS").
- **Body**:
  - Goal and scope.
  - Checklist of subtasks.
  - Links to relevant docs and tests.

Lifecycle pattern:

1. Open the issue at the start of the work.
2. Keep it updated as tasks are completed.
3. Reference the issue from related PRs (for example "Fixes #130").
4. Close the issue when all acceptance criteria are met and merged.

---

## 5. Snapshots, versions, and drift

Over time, controller prompts and ChatGPT snapshots can drift away from the actual code. To manage this:

- Include a small **version or commit reference** in the controller prompt or snapshot description (for example "Aligned with commit d0c7d94 on ally-mcp-github-refactor-fresh").
- Periodically re-sync the prompt with the live tool list and docs:
  - Re-run `list_all_actions`.
  - Scan for new tools or changed behaviors.
  - Update the prompt to reflect new capabilities or removed tools.

If you discover drift:

1. Note the mismatch in a GitHub issue.
2. Decide whether to change code, docs, or the controller prompt.
3. Implement the fix and close the loop by updating all three if needed.

---

## 6. Example assistant workflow for a docs change

Here is a concrete example of how an assistant might update docs safely:

1. **Identify the need**
   - Notice that a new tool (for example `create_issue`) is not yet documented in `docs/WORKFLOWS.md`.

2. **Open or update an issue**
   - If no issue exists, use `create_issue` to open one (for example "Docs: document issue tools").
   - If an issue already tracks this (for example #130), add a comment describing the planned docs change.

3. **Plan the edit**
   - Read the existing docs and tests.
   - Decide which sections need updating (for example the "Issues and lifecycle management" section in `WORKFLOWS.md`).

4. **Apply the change on a feature branch**
   - Use `ensure_branch` if necessary.
   - Use `get_file_contents` to fetch the current doc content.
   - Prepare an updated version of the doc section.
   - Use `apply_text_update_and_commit` to write the new content to the branch.

5. **Open a PR**
   - Use `update_files_and_open_pr` or PR helpers to open a PR with the docs change.
   - Reference the issue (for example "Docs: update workflows for issue tools (Fixes #130)").

6. **Close the loop**
   - After the PR is merged, close the issue.
   - Optionally update the controller prompt if the docs change reflects a new recommended pattern.

---

## 7. Mental model for assistants

Assistants working with this repo should adopt the following mental model:

- The **code and tests** define actual behavior.
- The **docs** summarize and explain that behavior for humans.
- The **controller prompts and snapshots** instruct ChatGPT how to use the tools based on those docs.

To stay aligned:

- Regularly consult the tests and docs when you are unsure.
- When adding or changing tools, think through the implications for all three layers.
- Treat inconsistencies as bugs and fix them via the usual issue + PR workflow.

By doing this, assistants help ensure that the Adaptiv Controller remains trustworthy, well-documented, and easy for both humans and AI to reason about over time.