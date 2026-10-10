#!/bin/sh
# mFruit OS entry point (manifest.json). mFruit OS runs it in the active
# version folder with WHISPLAY_OS_APP_DATA set: the API keys (.env), chat data
# and knowledge live there, so updates and reinstalls keep them. Without
# WHISPLAY_OS_APP_DATA (started by hand) it behaves like run_chatbot.sh.
cd "$(dirname "$0")" || exit 1
export PYTHONUNBUFFERED=1
# install.sh puts a Node.js runtime here when the system has no Node 20.
if [ -x runtime/bin/node ]; then
  PATH="$PWD/runtime/bin:$PATH"
  export PATH
fi
DATA="${WHISPLAY_OS_APP_DATA:-}"
if [ -n "$DATA" ]; then
  mkdir -p "$DATA/data" "$DATA/knowledge"
  for name in data knowledge; do
    [ -e "$name" ] || [ -L "$name" ] || ln -s "$DATA/$name" "$name"
  done
  if [ ! -f "$DATA/.env" ]; then
    exec python3 python/no_keys.py "$DATA/.env"
  fi
  ln -sfn "$DATA/.env" .env
fi
exec bash ./run_chatbot.sh "$@"
