#!/usr/bin/env sh
set -eu

# Verify vendored rg works (Render builds run on linux; keep this as a fast sanity check)
if [ -x "./vendor/rg/linux-x64/rg" ]; then
  ./vendor/rg/linux-x64/rg --version
fi

python -m pip install --upgrade pip

# Keep prod images small and deploys fast.
pip install -r dev-requirements.txt

# Optional: allow installing dev deps in Render for debugging.
if [ "${RENDER_INSTALL_DEV_DEPS:-}" = "1" ]; then
  pip install -r dev-requirements.txt
fi
