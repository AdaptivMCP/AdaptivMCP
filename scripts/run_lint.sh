#!/usr/bin/env bash
set -euo pipefail

# Lint suite should not install dependencies at runtime.
# Render deploy installs requirements; CI should install dependencies as part of the workflow.

echo "Running ruff format --check..."
python -m ruff format --check .

echo "Running ruff check..."
python -m ruff check .
