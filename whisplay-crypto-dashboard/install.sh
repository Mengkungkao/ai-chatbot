#!/usr/bin/env bash
# Installer for the Whisplay Bitcoin Market Dashboard (Raspberry Pi Zero 2 W).
#
#   ./install.sh              register with the Whisplay daemon
#   ./install.sh --autostart  also start automatically at boot
#   ./install.sh --uninstall  remove service + daemon registration
#
# Dependencies come from apt where possible: building Pillow or numpy from
# source with pip on a Pi Zero 2 W can take the better part of an hour.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="whisplay-crypto-dashboard"
SERVICE_NAME="whisplay-crypto.service"

TARGET_USER="${SUDO_USER:-$(whoami)}"
USER_HOME="$(eval echo "~${TARGET_USER}")"
TARGET_UID="$(id -u "$TARGET_USER")"

DAEMON_APPS_DIR="$USER_HOME/.whisplay-daemon/app"
LOG_DIR="/var/log/whisplay-crypto"

AUTOSTART=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --autostart) AUTOSTART=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

say()  { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[0;32mok\033[0m  %s\n' "$*"; }
warn() { printf '    \033[0;33m!!\033[0m  %s\n' "$*"; }

# ---------------------------------------------------------------- uninstall
if [ "$UNINSTALL" -eq 1 ]; then
  say "Uninstalling $APP_ID"
  if systemctl list-unit-files 2>/dev/null | grep -q "^$SERVICE_NAME"; then
    sudo systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
    sudo rm -f "/etc/systemd/system/$SERVICE_NAME"
    sudo systemctl daemon-reload
    ok "removed $SERVICE_NAME"
  fi
  rm -f "$DAEMON_APPS_DIR/$APP_ID.json" && ok "removed daemon registration"
  echo
  echo "Config, cache and logs were left in place:"
  echo "  $USER_HOME/.whisplay-crypto/    $LOG_DIR/"
  exit 0
fi

say "Installing Whisplay Bitcoin Market Dashboard"
echo "    app dir : $APP_DIR"
echo "    user    : $TARGET_USER"
echo

# ------------------------------------------------------------- dependencies
say "Checking Python"
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }
ok "$(python3 --version)"

say "Installing dependencies (apt preferred, pip as fallback)"
APT_PACKAGES=(python3-pil python3-requests python3-yaml python3-numpy python3-dotenv)
MISSING=()
for pkg in "${APT_PACKAGES[@]}"; do
  dpkg -s "$pkg" >/dev/null 2>&1 || MISSING+=("$pkg")
done

if [ "${#MISSING[@]}" -gt 0 ]; then
  if command -v apt-get >/dev/null 2>&1; then
    echo "    installing: ${MISSING[*]}"
    sudo apt-get update -qq || warn "apt update failed, continuing"
    sudo apt-get install -y "${MISSING[@]}" || warn "some apt packages failed"
  else
    warn "apt-get unavailable; skipping to pip"
  fi
fi

# Verify each import; fall back to pip only for what is genuinely missing.
for mod in PIL requests yaml; do
  python3 -c "import $mod" 2>/dev/null || {
    warn "$mod still missing, trying pip"
    python3 -m pip install --user -r "$APP_DIR/requirements.txt" || {
      echo "Failed to install Python dependencies" >&2; exit 1; }
    break
  }
done
python3 -c "import PIL, requests, yaml" || exit 1
ok "Pillow, requests, PyYAML available"
python3 -c "import numpy" 2>/dev/null \
  && ok "numpy available (fast RGB565 conversion)" \
  || warn "numpy missing: RGB565 conversion falls back to pure Python"
python3 -c "import dotenv" 2>/dev/null \
  || warn "python-dotenv missing: .env will not be auto-loaded"

# --------------------------------------------------------------------- env
say "Preparing configuration"
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  ok "created .env (no API key required for the default providers)"
else
  ok ".env already present, left untouched"
fi
[ -f "$APP_DIR/config.yaml" ] && ok "config.yaml present"

install -d -m 0755 "$USER_HOME/.whisplay-crypto"
chown "$TARGET_USER":"$TARGET_USER" "$USER_HOME/.whisplay-crypto" 2>/dev/null || true
ok "state dir: $USER_HOME/.whisplay-crypto"

say "Preparing log directory"
if sudo install -d -m 0755 -o "$TARGET_USER" -g "$TARGET_USER" "$LOG_DIR" 2>/dev/null; then
  ok "$LOG_DIR"
else
  warn "could not create $LOG_DIR; logging falls back to ~/.whisplay-crypto/app.log"
fi

chmod +x "$APP_DIR/run.sh"

# ------------------------------------------------------- daemon registration
say "Registering with the Whisplay daemon"
if [ -d "$USER_HOME/.whisplay-daemon" ]; then
  install -d -m 0755 "$DAEMON_APPS_DIR"
  sed "s|__APP_DIR__|$APP_DIR|g" \
    "$APP_DIR/packaging/$APP_ID.json" > "$DAEMON_APPS_DIR/$APP_ID.json"
  chown "$TARGET_USER":"$TARGET_USER" "$DAEMON_APPS_DIR/$APP_ID.json" 2>/dev/null || true
  ok "installed $DAEMON_APPS_DIR/$APP_ID.json"
  ok "appears on the Whisplay desktop as 'BTC Dashboard'"
else
  warn "$USER_HOME/.whisplay-daemon not found"
  warn "install the Whisplay daemon first: Whisplay/daemon/install_whisplay_daemon_service.sh"
  warn "the app still self-registers on first launch"
fi

# ------------------------------------------------------------- autostart
if [ "$AUTOSTART" -eq 1 ]; then
  say "Installing $SERVICE_NAME"
  sed -e "s|__APP_DIR__|$APP_DIR|g" \
      -e "s|__USER__|$TARGET_USER|g" \
      -e "s|__USER_HOME__|$USER_HOME|g" \
      -e "s|__UID__|$TARGET_UID|g" \
      "$APP_DIR/packaging/$SERVICE_NAME" | sudo tee "/etc/systemd/system/$SERVICE_NAME" >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"
  ok "enabled: starts automatically at boot"
  say "Starting now"
  sudo systemctl restart "$SERVICE_NAME"
  sleep 2
  systemctl is-active --quiet "$SERVICE_NAME" \
    && ok "$SERVICE_NAME is running" \
    || warn "not running yet -- check: journalctl -u $SERVICE_NAME -n 50"
fi

# ------------------------------------------------------------------ summary
echo
say "Installation complete"
cat <<SUMMARY

  Run it now (foreground):
      cd $APP_DIR && ./run.sh

  Launch from the Whisplay desktop:
      single click to select 'BTC Dashboard', then long press

  Controls:
      1 click    next timeframe (1H > 4H > 1D > 1W > 1Y)
      hold       next page      (Bitcoin > Market > Top > Stats > System)
      2 clicks   return HOME
      3 clicks   force refresh
      4 clicks   leave the app

  Autostart at boot:
      ./install.sh --autostart

  Logs:
      tail -f $LOG_DIR/app.log
      journalctl -u $SERVICE_NAME -f

SUMMARY
