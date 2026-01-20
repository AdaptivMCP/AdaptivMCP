#!/usr/bin/env sh
set -eu

# Verify vendored rg works (Render builds run on linux; keep this as a fast sanity check)
if [ -x "./vendor/rg/linux-x64/rg" ]; then
  ./vendor/rg/linux-x64/rg --version
fi

python -m pip install --upgrade pip

requirements_file="dev-requirements.txt"
marker_file=".deps-${requirements_file}.sha256"

if [ -f "$requirements_file" ]; then
  requirements_hash="$(python - <<'PY'
import hashlib
from pathlib import Path

path = Path("dev-requirements.txt")
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
)"

  if [ -f "$marker_file" ] && [ "$(cat "$marker_file")" = "$requirements_hash" ]; then
    echo "Dependencies already satisfied; skipping install."
  else
    # Keep prod images small and deploys fast.
    pip install -r "$requirements_file"
    printf '%s\n' "$requirements_hash" > "$marker_file"
  fi
else
  echo "No ${requirements_file} found; skipping dependency install."
fi

# Optional: allow re-installing dev deps in Render for debugging.
if [ "${RENDER_INSTALL_DEV_DEPS:-}" = "1" ]; then
  pip install -r "$requirements_file"
fi
