#!/bin/bash
# mFruit OS install hook: runs on install, update and reinstall, as the user,
# without sudo or questions. It downloads nothing: the release archive from
# github.com/Mengkungkao/ai-chatbot carries the app, its node_modules, the
# fonts and emoji, and Node.js in runtime/. It checks the system packages
# (installed once by mFruit OS: scripts/setup-app.sh whisplay-ai-chatbot) and
# that the bundled Node.js runs on this board. It never registers with
# whisplay-daemon.
set -euo pipefail
cd "$(dirname "$0")"

[ "$(uname -m)" = aarch64 ] || { echo "AI Chatbot needs a 64-bit ARM board (this is $(uname -m))."; exit 1; }
[ -f dist/index.js ] && [ -d node_modules ] || {
  echo "This is not a built AI Chatbot package (dist/ or node_modules/ missing):"
  echo "install the release archive from the Fruit Store, not the source."; exit 1; }

missing=()
for command in sox play rec mpg123 aplay amixer; do
  command -v "$command" >/dev/null 2>&1 || missing+=("$command")
done
for module in PIL numpy cairosvg spidev gpiod; do
  python3 -c "import $module" >/dev/null 2>&1 || missing+=("python3 $module")
done
if [ "${#missing[@]}" -gt 0 ]; then
  echo "AI Chatbot needs: ${missing[*]}."
  echo "Install them once over SSH: bash ~/.whisplay-os/system/current/scripts/setup-app.sh whisplay-ai-chatbot"
  exit 1
fi

node_ok() { "$1" -e 'process.exit(+process.versions.node.split(".")[0] >= 20 ? 0 : 1)' 2>/dev/null; }
if [ -x runtime/bin/node ] && node_ok runtime/bin/node; then
  echo "Node.js $(runtime/bin/node --version) (package)"
elif command -v node >/dev/null 2>&1 && node_ok node; then
  echo "Node.js $(node --version) (system)"
else
  echo "Node.js 20 is missing: install the release archive from the Fruit Store, not the source."
  exit 1
fi
echo "whisplay-ai-chatbot: dependencies ok"
