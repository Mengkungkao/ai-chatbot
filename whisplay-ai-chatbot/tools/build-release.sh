#!/usr/bin/env bash
# Build AI Chatbot's mFruit OS package for 64-bit ARM boards.
#
#   bash tools/build-release.sh [OUT_DIR]     (default: ./release)
#
# Produces OUT_DIR/whisplay-ai-chatbot-<version>-linux-arm64.tar.gz and its
# .sha256: the app folder's files (tracked or new, as .gitignore allows), the
# compiled dist/, production node_modules with only the linux-arm64 native
# binaries, the emoji set with the cat faces drawn in (python/ASSETS.md) and
# the official Node.js runtime in runtime/. The Fruit Store installs that
# archive and the device downloads nothing else.
# Needs an arm64 machine with Node.js 20 and internet (yarn packages and the
# Node.js runtime, both checked against their lockfile/SHA-256);
# .github/workflows/release.yml runs it on GitHub's ubuntu-24.04-arm runner.
#
# Left out to keep the download small (about 85 MB): the Picovoice ASR/TTS
# providers (@picovoice/*, loaded only when selected in .env) and the Docker,
# pi-gen and web-development folders.
set -euo pipefail

APP="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(mkdir -p "${1:-$APP/release}" && cd "${1:-$APP/release}" && pwd)"
VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$APP/manifest.json")"
NAME="whisplay-ai-chatbot-$VERSION-linux-arm64"
YARN=(npx --yes yarn@1.22.22)
FONT_SHA256=a9c048e539c7b8c37573aa0143f4ca33cd5ba85ca186c1e0bc70f94dd75caf93
EMOJI_SHA256=d82effaeeca5e41ee4db5c7de4c162662670eac3243279478e281c02e460ab98
NODE_VERSION=20.19.5
NODE_SHA256=d462267863ae8ee556039ebdf559055a8ec562c633889ef1403f3adb449ba1dd   # linux-arm64.tar.xz

[ "$(uname -m)" = aarch64 ] || { echo "build on arm64: node_modules ships arm64 binaries" >&2; exit 1; }
node -e 'process.exit(+process.versions.node.split(".")[0] === 20 ? 0 : 1)' \
  || { echo "Node.js 20 is required to build (found $(node --version))" >&2; exit 1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
PKG="$WORK/whisplay-ai-chatbot"
mkdir -p "$PKG"
echo "==> files ($APP)"
(cd "$APP" && git ls-files -z --cached --others --exclude-standard) \
  | (cd "$APP" && tar --null -T - -cf -) | tar -xf - -C "$PKG"
rm -rf "$PKG/docker" "$PKG/packaging" "$PKG/release" "$PKG/tools/build-release.sh"

cd "$PKG"
echo "==> dependencies and build"
"${YARN[@]}" install --frozen-lockfile --non-interactive
NODE_OPTIONS=--max-old-space-size=2048 node_modules/.bin/tsc
"${YARN[@]}" install --production --frozen-lockfile --non-interactive --ignore-scripts
npx --yes patch-package@8.0.1            # postinstall was skipped by --ignore-scripts
rm -rf node_modules/typescript node_modules/ts-node node_modules/tsconfig-paths \
       node_modules/patch-package node_modules/@types node_modules/@picovoice
# onnxruntime-node ships every platform's binaries; keep linux-arm64.
find node_modules/onnxruntime-node/bin -mindepth 2 -maxdepth 2 ! -name linux -exec rm -rf {} +
find node_modules/onnxruntime-node/bin -path '*/linux/*' -mindepth 3 -maxdepth 3 ! -name arm64 \
  -exec rm -rf {} +

# Type declarations, source maps and docs are not needed to run (about 6,000
# files; mFruit OS refuses packages with more than 20,000).
find node_modules -type f \( -name '*.d.ts' -o -name '*.d.mts' -o -name '*.d.cts' \
  -o -name '*.map' -o -name '*.md' -o -name '*.markdown' \) -delete
find node_modules -xtype l -delete       # .bin links to the removed build tools

echo "==> fonts and emoji (from the repository)"
printf '%s  %s\n' "$FONT_SHA256" python/NotoSansSC-Bold.ttf "$EMOJI_SHA256" python/emoji_svg.zip \
  | sha256sum -c --quiet - || { echo "python/NotoSansSC-Bold.ttf or emoji_svg.zip changed" >&2; exit 1; }
python3 -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
  python/emoji_svg.zip python
rm python/emoji_svg.zip
# The zip holds the stock emoji; the cat faces replace them at their
# codepoints. face_gen.py also rewrites faces.json, which must not change.
python3 python/face_gen.py --json "$WORK/faces.json"
cmp -s "$WORK/faces.json" python/faces.json \
  || { echo "faces.json is out of date: run python3 python/face_gen.py and commit it" >&2; exit 1; }

echo "==> Node.js $NODE_VERSION runtime"
# Only the node binary and its licence: npm, headers and docs stay out.
curl -fsSL -o "$WORK/node.tar.xz" \
  "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-arm64.tar.xz"
echo "$NODE_SHA256  $WORK/node.tar.xz" | sha256sum -c --quiet - \
  || { echo "Node.js download does not match its SHA-256" >&2; exit 1; }
python3 - "$WORK/node.tar.xz" "node-v$NODE_VERSION-linux-arm64" runtime <<'PY'
import os, shutil, sys, tarfile
archive, top, dest = sys.argv[1:]
os.makedirs(os.path.join(dest, "bin"))
with tarfile.open(archive) as tar:
    for name, target in ((f"{top}/bin/node", "bin/node"), (f"{top}/LICENSE", "LICENSE")):
        with tar.extractfile(name) as src, open(os.path.join(dest, target), "wb") as out:
            shutil.copyfileobj(src, out)
os.chmod(os.path.join(dest, "bin", "node"), 0o755)
PY
runtime/bin/node -e 'process.exit(process.version === "v'"$NODE_VERSION"'" ? 0 : 1)'

echo "==> archive"
find . -name __pycache__ -prune -exec rm -rf {} +
tar --sort=name --owner=0 --group=0 --numeric-owner -C "$WORK" -czf "$OUT/$NAME.tar.gz" \
  whisplay-ai-chatbot
(cd "$OUT" && sha256sum "$NAME.tar.gz" > "$NAME.tar.gz.sha256")
echo "$OUT/$NAME.tar.gz: $(du -h "$OUT/$NAME.tar.gz" | cut -f1), $(find "$PKG" -type f | wc -l) files"
cat "$OUT/$NAME.tar.gz.sha256"
