Adaptiv MCP Server - Self Hosted MCP Server -
Backend: Render.com -
App User: MCP clients

## Documentation

- [Validation logic](docs/validation.md)

## Workspace mirrors

Workspace mirrors ensure the local git `origin` remote stays aligned with the
repo slug used to create the mirror so follow-on fetch/push operations target
the expected GitHub repository.

## Development setup

This project requires Python 3.11+ (needed for `typing.NotRequired` and
`datetime.UTC`). Create a virtual environment and install dependencies with:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run the test suite with:

```bash
pytest
```
