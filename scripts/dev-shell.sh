#!/usr/bin/env sh
# Launch an interactive shell with vendored `rg` available on PATH.
#
#   ./scripts/dev-shell.sh
#   rg --version

set -eu

# shellcheck disable=SC1091
. "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/rg-path.sh"

# Prefer user's shell if set; fall back to bash, then sh.
if [ -n "${SHELL:-}" ] && [ -x "${SHELL}" ]; then
  exec "${SHELL}"
elif command -v bash >/dev/null 2>&1; then
  exec bash
else
  exec sh
fi
