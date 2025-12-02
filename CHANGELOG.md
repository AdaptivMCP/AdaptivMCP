# Changelog

All notable changes to this project will be documented in this file.

This project follows semantic versioning (MAJOR.MINOR.PATCH).

## [1.0.0] - Initial 1.0 release

### Versioning and release metadata
- Lock project version to `1.0.0` in `pyproject.toml`.
- Introduce `CHANGELOG.md` as the canonical source of human-readable release notes.
- Define `1.0.0` as the baseline for subsequent 1.x releases.

### Controller contract and assistant behavior
- Evolve `controller_contract()` to document the full tool surface, safety model, and assistant expectations for Adaptiv Controller.
- Require assistants to treat the controller contract as the authoritative source of truth and to avoid inventing parallel "doc contracts".
- Encode expectations for branch-first, patch-first, PR-first workflows and strict JSON/tool schema usage.

### Core tooling and safety model
- Maintain strong write gating using `WRITE_ALLOWED` and the `authorize_write_actions` tool.
- Provide high-level GitHub tools for reading and writing repos (branches, commits, diffs, PRs, issues) with verification and read-after-write checks.
- Support workspace execution via `run_command` and `run_tests` for installing dependencies, running linters, and executing test suites in a persistent workspace.

### CI, CLI, and health
- Add a minimal `cli.py` that reads the project version from `pyproject.toml` and exposes a stable `python cli.py --version` entry point.
- Configure GitHub Actions CI (`.github/workflows/ci.yml`) to run `pytest -q` and a `python cli.py --version` smoke check on pushes and PRs.
- Expose `/healthz` with process health, controller configuration, and an in-memory metrics snapshot for MCP tools and GitHub client usage.

### Documentation and workflows
- Update `README.md` to describe the Adaptiv Controller GitHub Kit, versioning, and CI expectations.
- Flesh out `docs/SELF_HOSTED_SETUP.md` with a self-hosted deployment guide and a dedicated section on versioning and CLI checks.
- Flesh out `docs/UPGRADE_NOTES.md` as the source of truth for install, upgrade, and rollback flows (staging first, tags/branches, Render guidance).
- Update `docs/WORKFLOWS.md` so every new ChatGPT session:
  - Calls `controller_contract`.
  - Uses `run_command` to run `python cli.py --version` and confirm the server version (1.0.0 for this release).
  - Refreshes key docs from `main` (ASSISTANT_HANDOFF, WORKFLOWS, ARCHITECTURE_AND_SAFETY, ASSISTANT_DOCS_AND_SNAPSHOTS, SELF_HOSTED_SETUP).
- Maintain `ASSISTANT_HANDOFF.md` as the living handoff document for assistants, ensuring new chats can re-sync with the project state and expectations.

### Test suite
- Keep the test suite green on `main` (currently 86 tests) covering controller contract structure, repo helpers, JSON validation, and core behaviors.
