#!/usr/bin/env bash
set -euo pipefail

# Install project dependencies (including lint/format tools) into the active
# environment before running the lint suite. This keeps the script usable
# both in CI and from the controller-managed temp venv.
python -m pip install -r requirements.txt

echo "Running ruff..."
python -m ruff check .

echo "Running black --check..."
python -m black --check .

echo "Running isort --check-only..."
python -m isort github_mcp tests main.py extra_tools.py --check-only

echo "Running flake8..."
python -m flake8 github_mcp tests main.py extra_tools.py
