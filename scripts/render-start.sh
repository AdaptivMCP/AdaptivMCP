#!/usr/bin/env sh
set -eu

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64|amd64)
    RG_BIN="$ROOT_DIR/vendor/rg/linux-x64/rg"
    ;;
  aarch64|arm64)
    RG_BIN="$ROOT_DIR/vendor/rg/linux-arm64/rg"
    ;;
  *)
    echo "Unsupported architecture: $ARCH" >&2
    exit 1
    ;;
 esac

if [ ! -x "$RG_BIN" ]; then
  echo "rg binary missing or not executable: $RG_BIN" >&2
  exit 1
fi

export PATH="$(dirname "$RG_BIN"):$PATH"

# Verify rg is available and working before starting the server
command -v rg >/dev/null 2>&1
rg --version

UVICORN_WORKERS="${WEB_CONCURRENCY:-1}"
UVICORN_LOG_LEVEL="${LOG_LEVEL:-info}"

exec uvicorn main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${UVICORN_WORKERS}" \
  --log-level "${UVICORN_LOG_LEVEL}" \
  --proxy-headers \
  --forwarded-allow-ips "*"
