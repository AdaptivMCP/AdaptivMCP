#!/usr/bin/env bash
set -euo pipefail

# Test suite should never install dependencies at runtime.
# Render deploy installs requirements; CI handles its own environment.

python -m pytest
