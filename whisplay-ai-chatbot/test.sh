#!/bin/sh
# Smoke test ("test" in manifest.json): runs after install, before activation;
# a non-zero exit keeps the previous version. It loads nothing that writes
# files (the app creates data/ when it starts), and never touches the screen,
# the audio or the network.
set -e
export PYTHONDONTWRITEBYTECODE=1
cd "$(dirname "$0")"
[ -x runtime/bin/node ] && PATH="$PWD/runtime/bin:$PATH"
node --check dist/index.js
node -e 'for (const m of ["koa", "ws", "dotenv", "openai", "@anthropic-ai/sdk"]) require.resolve(m)'
cd python
python3 -c "import whisplay_client, utils, face_engine, boot_animation, keyboard_input, mfruit_sdk.ui"
echo "whisplay-ai-chatbot: test passed"
