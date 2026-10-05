#!/bin/bash
# MFruit OS install hook: runs on install, update and reinstall, as the user,
# without sudo or questions. It checks the system packages (installed once by
# MFruit OS: scripts/setup-app.sh whisplay-ai-chatbot) and provides Node.js 20:
# the system's when it is new enough, otherwise the official build, checked
# against its SHA-256, in runtime/. It never registers with whisplay-daemon.
set -euo pipefail
cd "$(dirname "$0")"
NODE_VERSION=20.19.5
NODE_SHA256=d462267863ae8ee556039ebdf559055a8ec562c633889ef1403f3adb449ba1dd   # linux-arm64.tar.xz

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
if command -v node >/dev/null 2>&1 && node_ok node; then
  echo "Node.js $(node --version) (system)"
elif [ -x runtime/bin/node ] && node_ok runtime/bin/node; then
  echo "Node.js $(runtime/bin/node --version) (package)"
else
  echo "Downloading Node.js $NODE_VERSION…"
  python3 - "$NODE_VERSION" "$NODE_SHA256" <<'PY'
import hashlib, os, shutil, sys, tarfile, tempfile, urllib.request
version, expected = sys.argv[1], sys.argv[2]
name = f"node-v{version}-linux-arm64"
url = f"https://nodejs.org/dist/v{version}/{name}.tar.xz"
with tempfile.TemporaryDirectory(dir=".") as work:
    archive = os.path.join(work, "node.tar.xz")
    digest = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, open(archive, "wb") as out:
        for block in iter(lambda: response.read(1 << 16), b""):
            digest.update(block)
            out.write(block)
    if digest.hexdigest() != expected:
        sys.exit(f"Node.js download does not match its SHA-256 ({url})")
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            inside = member.name == name or member.name.startswith(name + "/")
            if not inside or ".." in member.name.split("/"):
                sys.exit(f"unexpected path in the Node.js archive: {member.name}")
        safe = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(work, **safe)
    unpacked = os.path.join(work, name)
    # Only the node binary is used: npm, corepack, headers and docs stay out.
    for extra in ("include", "share", os.path.join("lib", "node_modules"),
                  os.path.join("bin", "npm"), os.path.join("bin", "npx"),
                  os.path.join("bin", "corepack")):
        path = os.path.join(unpacked, extra)
        if os.path.islink(path) or os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            shutil.rmtree(path)
    shutil.rmtree("runtime", ignore_errors=True)
    os.rename(unpacked, "runtime")
PY
  node_ok runtime/bin/node || { echo "The downloaded Node.js does not run on this board."; exit 1; }
  echo "Node.js $(runtime/bin/node --version) (package)"
fi
echo "whisplay-ai-chatbot: dependencies ok"
