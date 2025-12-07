#!/usr/bin/env bash
set -euo pipefail

# Ensure pytest is available in the active environment (including the temp venv
# used by run_command) before running the test suite.
python -m pip install pytest
python -m pytest
