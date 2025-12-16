#!/usr/bin/env bash
set -euo pipefail

# Ensure the test environment has the project dependencies (including pytest)
# installed into the active environment/temp venv before running the suite.
python -m pip install -r dev-requirements.txt
python -m pytest
