#!/usr/bin/env sh
set -eu

# Bootstrap a local development virtualenv.
#
# Examples:
#   ./scripts/bootstrap.sh
#   ./scripts/bootstrap.sh --run-tests

python scripts/bootstrap.py "$@"
