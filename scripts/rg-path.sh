#!/usr/bin/env sh
# Source this file to make the vendored ripgrep (`rg`) available on PATH.
#
#   . ./scripts/rg-path.sh
#   rg --version
#
# This script is intended to be sourced. It uses `git rev-parse --show-toplevel`
# to locate the repository root, which works regardless of how the script is
# invoked.

set -eu

ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64|amd64)
    RG_DIR="$ROOT_DIR/vendor/rg/linux-x64"
    ;;
  aarch64|arm64)
    RG_DIR="$ROOT_DIR/vendor/rg/linux-arm64"
    ;;
  *)
    echo "Unsupported architecture for vendored rg: $ARCH" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

RG_BIN="$RG_DIR/rg"
if [ ! -x "$RG_BIN" ]; then
  echo "Vendored rg binary missing or not executable: $RG_BIN" >&2
  echo "If you are on a non-Linux system, install ripgrep via your package manager (e.g., brew/apt)." >&2
  return 1 2>/dev/null || exit 1
fi

# Prepend to PATH.
export PATH="$RG_DIR:$PATH"
