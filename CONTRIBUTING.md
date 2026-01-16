# Contributing

This repository is the source code for the Adaptiv GitHub MCP server.

Principle: the Python code is the source of truth. Documentation and tests must follow the behavior of the code.

## Local development

1) Create a virtualenv and install dependencies

- `make install-dev`

2) Run the server

```bash
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

3) Run quality checks

- `make format`
- `make lint`
- `make test`

## Documentation workflow

### Regenerating the tool catalog

`Detailed_Tools.md` is generated from the running tool registry via `main.list_all_actions(...)`.

If you add/remove tools or change tool signatures, regenerate it:

```bash
python scripts/generate_detailed_tools.py
```

Then commit the updated file alongside code changes. CI enforces that the generated
catalog is up to date.

### Updating usage and safety docs

- `docs/usage.md` should describe stable behavior and configuration.
- `docs/architecture_safety.md` should describe safety boundaries and guardrails.

When there is any mismatch, update the docs to align with code.
