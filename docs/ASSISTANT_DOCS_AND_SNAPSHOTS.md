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
  - `docs/ARCHITECTURE_AND_SAFETY.md` for deeper internals and guarantees.
  - `docs/SELF_HOSTED_SETUP.md` for deployment and operator guidance.

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

- Include a small **version or commit reference** in the controller prompt or snapshot description (for example "Aligned with commit d0c7d94 on main").
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


For very large files (especially `main.py` and other core modules), assistants should avoid shuttling whole-file contents back and forth. Instead, use the large-file orchestration and JSON helpers exposed by the controller.

### 8.1 Inspecting large files safely

- Use `get_file_slice` to read only the relevant region of a file:
  - Provide `full_name`, `path`, `ref`, `start_line`, and `max_lines`.
  - Use `has_more_above` / `has_more_below` and `total_lines` to navigate.
- Prefer reading a few slices around the area you plan to edit rather than the entire file.

### 8.2 Building section-based patches

When you know the line ranges that need to change, construct a `sections` array and use `build_section_based_diff`:

- Each section has:
  - `start_line`: 1-based inclusive start.
  - `end_line`: 1-based inclusive end (or `start_line - 1` for pure inserts).
  - `new_text`: the replacement text for that region.
- Sections must be:
  - Sorted by `start_line`.
  - Non-overlapping.
- Call `build_section_based_diff(full_name, path, sections, ref, context_lines)` to get a unified diff patch.
- The tool will refuse to run if `sections` is missing, if ranges overlap, or if line numbers fall outside the file.
- Apply the returned `patch` using `apply_patch_and_commit` on the same branch.

This pattern keeps diffs small and precise, even for very large files, and its refusal modes make it clear when the input is unsafe.

### 8.3 Choosing the right diff builder

You now have two diff builders with explicit safety behaviors:

- `build_unified_diff(full_name, path, ref, new_content, context_lines)`
  - Fetches the current file from GitHub and builds a diff against `new_content`.
  - Rejects negative `context_lines` and bubbles GitHub errors (missing file, ref, or permissions) instead of guessing.
- `build_unified_diff_from_strings(original, updated, path, context_lines)`
  - Use this when you already have both buffers in memory.
  - Rejects negative `context_lines` so patches stay well-formed.

Both tools keep the assistant in a patch-first workflow without having to hand-write unified diff strings.

### 8.4 Validating JSON with `validate_json_string`

When returning JSON to a client or passing JSON into other tools (such as long `sections` arrays), use `validate_json_string` to catch mistakes before they cause errors:

1. Build the JSON string you intend to use (for example, the `sections` array for `build_section_based_diff`).
2. Call `validate_json_string` with that raw string.
3. If `ok` is true, use the `normalized` JSON string as your final output.
4. If `ok` is false, examine `error`, fix the problem (missing quotes, trailing commas, etc.), and try again.

By combining `get_file_slice`, `build_section_based_diff`, `build_unified_diff` (or `build_unified_diff_from_strings` when you already have the buffers), `apply_patch_and_commit`, and `validate_json_string`, assistants can safely edit large files and produce strict JSON outputs without falling into read-only loops or brittle manual diff construction.

## 9. Execution environment for assistants

When planning or describing workflows, assistants must treat `run_command` and `run_tests` as the canonical way to execute code and tests against this repository (and any other repo accessed through this controller).

Key points:

- These tools clone the target repo at the effective ref into a temporary workspace and optionally create a temporary virtual environment.
- Commands and tests run **inside that workspace**, not in the long-lived MCP server process.
- After the command finishes, the workspace is discarded; any project-level dependencies must be installed per-workspace as needed.

Implications for prompts and snapshots:

- Do not assume that packages are globally installed in the controller process; instead, assume that `run_command` / `run_tests` will handle any necessary setup in the cloned workspace.
- When you design prompts or higher-level workflows, explicitly mention these tools as the default execution environment for running tests or CLI tools.
- When new tools are added that rely on code execution, they should internally use this same workspace model.

## 10. Summary

By doing this, assistants help ensure that the Adaptiv Controller remains trustworthy, well-documented, and easy for both humans and AI to reason about over time.
