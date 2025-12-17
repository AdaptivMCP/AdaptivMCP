#!/usr/bin/env bash
set -euo pipefail

# Install project dependencies (including lint/format tools) into the active
# environment before running the lint suite. This keeps the script usable
# both in CI and from the controller-managed temp venv.
python -m pip install -r dev-requirements.txt

echo "Running ruff format --check..."
python -m ruff format --check .

echo "Running ruff check..."
python -m ruff check .
