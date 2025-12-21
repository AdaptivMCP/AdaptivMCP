# Adaptiv Controller preferences

This optional file lets you describe how you want your Adaptiv-powered assistant to behave over time. It is a human-readable contract between you and your controller prompts so the AI can quickly learn and remember your preferences.

The canonical location is:

- docs/adaptiv/preferences.md in your controller repository.

## How this file is used

At a high level, this file is meant to be read by your ChatGPT assistant at the start of a session or whenever you ask it to recap your preferences. A typical controller prompt will tell the assistant to look for this file and respect what it says.

Nothing in the MCP server enforces these preferences automatically. Instead, they are guidance the assistant is expected to honor when it chooses tools, branch names, commit messages, and how aggressively to refactor.

## Recommended sections

- Coding style – language conventions, formatting expectations, comments, and how much explanation you want in PRs.
- Branch and PR habits – branch naming, PR size, and when to split work into multiple PRs.
- Testing and tooling – which test commands matter most and when it is acceptable to open a PR with failing tests.
- Risk tolerance – how comfortable you are with refactors, dependency upgrades, or touching unfamiliar areas of the codebase.
- Communication tone – how formal or informal you want commit messages, PR descriptions, and assistant explanations to be.
- Progress and communication – how often you want inline updates during multi-step work, and whether the assistant should keep going by default.

## Example outline

# My Adaptiv preferences

## Coding style

- Primary languages I care about.
- Follow the linters and formatters already configured in the repo.
- Prefer small, focused changes with clear diffs over huge multi file rewrites.

## Branch and PR habits

- Branch names: use feat, fix, or chore prefixes with short, descriptive slugs.
- Never push directly to main; always work on a feature branch and open a PR.

## Testing and tooling

- Run the standard test command before asking me to review a PR when it is practical to do so.
- If tests or lint fail, summarize the failure and suggest a follow up plan instead of hiding it.

## Communication

- Be concise but clear in explanations.
- In PR descriptions, clearly list what changed, why, and how it was tested.

## Progress and communication

- During multi-step tasks (for example creating a branch, updating code, running tests, and opening a PR), provide brief inline updates as you go instead of only at the end.
- Each update should say what you just did, what you learned (for example test results or CI state), and what you plan to do next.
