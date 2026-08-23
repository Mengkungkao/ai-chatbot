#!/usr/bin/env bash
# Startup wrapper for the Whisplay Bitcoin Market Dashboard.
#
# Waits for the Whisplay daemon socket before launching, so that starting
# at boot does not race the daemon and fall back to direct hardware mode.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

DAEMON_SOCKET="${WHISPLAY_DAEMON_SOCKET:-/tmp/whisplay-daemon.sock}"
DAEMON_WAIT_SECONDS="${WHISPLAY_DAEMON_WAIT:-30}"

# Prefer a project virtualenv when one exists.
if [ -x "$APP_DIR/.venv/bin/python3" ]; then
  PYTHON_BIN="$APP_DIR/.venv/bin/python3"
else
  PYTHON_BIN="$(command -v python3)"
fi

if [ -z "${PYTHON_BIN:-}" ]; then
  echo "whisplay-crypto: python3 not found" >&2
  exit 1
fi

# Wait for the daemon, but never block forever: the app runs standalone
# (direct hardware access) if the daemon never appears.
waited=0
while [ ! -S "$DAEMON_SOCKET" ] && [ "$waited" -lt "$DAEMON_WAIT_SECONDS" ]; do
  sleep 1
  waited=$((waited + 1))
done

if [ -S "$DAEMON_SOCKET" ]; then
  echo "whisplay-crypto: daemon socket ready after ${waited}s"
else
  echo "whisplay-crypto: daemon socket not found after ${waited}s; starting anyway"
fi

exec "$PYTHON_BIN" "$APP_DIR/app/main.py"
