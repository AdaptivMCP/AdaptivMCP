# Documentation + module docstring refresh (2025-12-17)

## Why

The repo had drift between:

- the live tool surface,
- the actual code layout,
- and the operator/assistant documentation.

This refresh makes the documentation a true reflection of the current engine and improves maintainability by adding module-level docstrings.

## What changed

### Docs (rewritten / regenerated)

- `GETTING_STARTED.md` – updated deploy + connect + verify flow (Render + Docker).
- `index.md` – tightened into a simple docs landing page.
- `Detailed_Tools.md` – regenerated from the runtime tool registry and grouped by intent.
- `controller_tool_map.md` – regenerated from code decorators to map tools → files/lines.
- `CHANGELOG.md` – rewritten to a clear operator-facing changelog.
- `ProofOfConcept.md` – updated to use current tool names and current minimal workflows.

### Assistant playbooks

- Rewrote:
  - `docs/assistant/ASSISTANT_HANDOFF.md`
  - `docs/assistant/ASSISTANT_HAPPY_PATHS.md`
  - `docs/assistant/ASSISTANT_DOCS_AND_SNAPSHOTS.md`

These now align with:

- the branch-first default,
- the explicit “direct-to-main” mode for the controller engine repo,
- the logging contract (“logs are UI”),
- and the quality gates.

### Architecture doc

- Rewrote `docs/human/ARCHITECTURE_AND_SAFETY.md` to reflect the current folder layout, tool registration model, write gate, logging contract, and debugging surfaces.

### Links + references

- Updated internal links to the canonical `docs/human/*` paths.
- Updated `.env.example` references away from the legacy `run_command` name.

### Code maintainability

- Added module-level docstrings to Python modules that were missing them (primarily under `github_mcp/`).

## Verification

- Ran `./scripts/run_ci.sh`:
  - `ruff format --check`: PASS
  - `ruff check`: PASS
  - `pytest`: PASS (231 tests)

## Notes / follow-ups

- Tool categorization in `Detailed_Tools.md` is intentionally heuristic; the runtime tool surface remains the source of truth.
- If new tools are added, regenerate `Detailed_Tools.md` and `controller_tool_map.md` as part of the PR/commit.
