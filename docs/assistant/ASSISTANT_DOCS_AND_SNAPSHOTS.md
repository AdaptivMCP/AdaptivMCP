# Docs and snapshots

This repo treats documentation as part of the controller contract.

## Canonical docs

- `README.md` – product overview and expectations.
- `GETTING_STARTED.md` – deploy/connect quickstart.
- `docs/human/WORKFLOWS.md` – how assistants should behave (branching, quality gates, shipping).
- `docs/human/OPERATIONS.md` – CI + provider (Render) guidance.
- `docs/human/ARCHITECTURE_AND_SAFETY.md` – architecture + write gate + safety model.
- `Detailed_Tools.md` – tool names + summaries.
- `controller_tool_map.md` – where each tool is defined in code.

## Runtime truth

If any doc disagrees with runtime behavior, treat runtime as the source of truth and fix the doc.

Use:

- `list_all_actions` to enumerate tools.
- `describe_tool` to get exact schemas and descriptions.
- `get_server_config` to verify runtime defaults.

## Session logs

All meaningful work sessions should create or append a repo-local session log entry under:

- `session_logs/`

These files are intended to be reviewed by humans. Write them like a concise engineering journal:

- what changed,
- why it changed,
- what was verified,
- what remains.

## Snapshots (recommended practice)

Before a risky refactor:

1. Create a short “snapshot” note in `session_logs/` with:
   - current behavior,
   - current failing tests/CI if any,
   - intended end state.
2. Make changes behind quality gates.
3. After shipping, append the “after” state.

This keeps the controller engine maintainable even as tool surfaces evolve.
