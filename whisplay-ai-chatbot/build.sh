#!/bin/bash
cd "$(dirname "$0")" || exit 1

# Node is installed per-user (nvm in ~/.nvm), so building as root can't find
# npm and would leave root-owned node_modules/dist. If invoked via sudo, drop
# back to the calling user.
if [ "$(id -u)" -eq 0 ] && [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
  echo "build.sh should not be run with sudo; re-running as '$SUDO_USER'..."
  exec sudo -u "$SUDO_USER" -H env NPM_REGISTRY="$NPM_REGISTRY" bash "$0" "$@"
fi

NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmjs.org}"

# if file use_npm exists and is true, use npm
if [ -f "use_npm" ]; then
  use_npm=true
else
  use_npm=false
fi

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# check if .env file exists
if [ ! -f .env ]; then
    echo "Please create a .env file with the necessary environment variables. Please refer to .env.template for guidance."
    exit 1
fi

[ -f ~/.bashrc ] && source ~/.bashrc

# ~/.bashrc usually returns early for non-interactive shells, so load Node
# explicitly: nvm (aarch64/armv7) or the /opt/nodejs binary (armv6l).
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -d /opt/nodejs/bin ] && export PATH="/opt/nodejs/bin:$PATH"

if ! command_exists npm; then
  echo "ERROR: npm not found. Node.js 20 is not installed for user '$(whoami)'."
  echo "Run 'bash install_dependencies.sh' (without sudo), then 'source ~/.bashrc' and retry."
  exit 1
fi

if [ "$use_npm" = true ]; then
  echo "Using npm to build the project."
  npm install --registry=$NPM_REGISTRY
  npm run build
else
  if ! command -v yarn >/dev/null 2>&1; then
    echo "WARNING: yarn not found. Falling back to npm."
    use_npm=true
  fi

  if [ "$use_npm" = true ]; then
    echo "Using npm to build the project."
    npm install --registry=$NPM_REGISTRY
    npm run build
  else
    echo "Using yarn to build the project."
    if ! yarn --registry=$NPM_REGISTRY || ! yarn build; then
      echo "WARNING: yarn failed. Falling back to npm."
      npm install --registry=$NPM_REGISTRY
      npm run build
    fi
  fi
fi