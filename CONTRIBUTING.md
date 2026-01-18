# Contributing

This repository is the source code for the Adaptiv GitHub MCP server.

Principle: runtime behavior is governed by the Python code. Documentation and tests must follow the behavior of the code.

## Local development

Local development uses a standard Python virtual environment and the same HTTP entrypoint used in production.

Environment bootstrap:

- `make bootstrap` (or `python scripts/bootstrap.py`)

Manual virtualenv flows are supported; `make install-dev` installs development dependencies into the active environment.

Local server entrypoint:

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Quality checks:

- `make format`
- `make lint`
- `make test`

## Documentation workflow

### Regenerating the tool catalog

`Detailed_Tools.md` is generated from the running tool registry via `main.list_all_actions(...)`.

Tool catalog updates track the registered tool set and their schemas. When tool registration changes, the catalog is regenerated with:

```bash
python scripts/generate_detailed_tools.py > Detailed_Tools.md
```

The generated file is committed alongside the code change that modified the tool surface.

### Updating usage and safety docs

- `docs/usage.md` describes stable behavior and configuration.
- `docs/architecture_safety.md` describes safety boundaries and guardrails.

Documentation reflects runtime behavior as implemented by the Python code.
