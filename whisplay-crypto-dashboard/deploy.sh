#!/usr/bin/env bash
# Copy this project to a Raspberry Pi and optionally install it there.
#
#   ./deploy.sh jarvis@192.168.1.112
#   ./deploy.sh jarvis@raspberrypi.local --install
#   ./deploy.sh jarvis@192.168.1.50 --install --autostart
#
# Uses rsync when available (fast incremental re-deploys), else scp.
set -euo pipefail

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "usage: ./deploy.sh user@host [--install] [--autostart]" >&2
  exit 1
fi
shift

DO_INSTALL=0
INSTALL_ARGS=""
for arg in "$@"; do
  case "$arg" in
    --install)   DO_INSTALL=1 ;;
    --autostart) DO_INSTALL=1; INSTALL_ARGS="--autostart" ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="$(basename "$APP_DIR")"
REMOTE_DIR="~/$NAME"

echo "==> Checking $TARGET is reachable"
if ! ssh -o ConnectTimeout=25 -o BatchMode=yes "$TARGET" 'echo ok' >/dev/null 2>&1; then
  echo "    cannot reach $TARGET over SSH (key auth)." >&2
  echo "    check: the Pi is powered on, SSH is enabled (sudo raspi-config)," >&2
  echo "           the address is right, and your key is installed" >&2
  echo "           (ssh-copy-id $TARGET)." >&2
  exit 1
fi
echo "    ok: $(ssh "$TARGET" 'hostname')"

echo "==> Copying project to $TARGET:$REMOTE_DIR"
# .env holds secrets and stays on the device; caches and venvs are local junk.
EXCLUDES=(--exclude '.git' --exclude '__pycache__' --exclude '*.pyc'
          --exclude '.venv' --exclude '.pytest_cache' --exclude '.env')

if command -v rsync >/dev/null 2>&1; then
  rsync -az --delete "${EXCLUDES[@]}" "$APP_DIR/" "$TARGET:$REMOTE_DIR/"
else
  ssh "$TARGET" "mkdir -p $REMOTE_DIR"
  TMP="$(mktemp -d)"
  tar czf "$TMP/app.tgz" -C "$(dirname "$APP_DIR")" \
    --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.venv' --exclude='.pytest_cache' --exclude='.env' "$NAME"
  scp -q "$TMP/app.tgz" "$TARGET:/tmp/whisplay-crypto-deploy.tgz"
  ssh "$TARGET" "tar xzf /tmp/whisplay-crypto-deploy.tgz -C ~ && rm -f /tmp/whisplay-crypto-deploy.tgz"
  rm -rf "$TMP"
fi
ssh "$TARGET" "chmod +x $REMOTE_DIR/run.sh $REMOTE_DIR/install.sh $REMOTE_DIR/deploy.sh"
echo "    copied"

if [ "$DO_INSTALL" -eq 1 ]; then
  echo "==> Running install.sh $INSTALL_ARGS on $TARGET"
  ssh -t "$TARGET" "cd $REMOTE_DIR && ./install.sh $INSTALL_ARGS"
else
  echo
  echo "Next, on the Pi:"
  echo "    ssh $TARGET"
  echo "    cd $NAME && ./install.sh --autostart"
fi
