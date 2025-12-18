#!/usr/bin/env bash
set -euo pipefail

# Lint suite should not install dependencies at runtime.
# The service environment is prepared at deploy time; CI manages its own environment.

# NOTE: ruff format will attempt to parse files it is asked to format.
# We only format/check Python sources here.

echo "Running ruff format --check (python only)..."
python -m ruff format --check . --exclude README.md --exclude "*.md"

echo "Running ruff check..."
python -m ruff check .
