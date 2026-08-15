#!/usr/bin/env sh
# Memento one-command installer (uv-based).
#
#   Local repo:   ./scripts/install.sh
#   Remote:       curl -LsSf https://raw.githubusercontent.com/c0mpli/memento/main/scripts/install.sh | sh
#
# Installs uv if missing, installs Memento as an isolated uv tool, then
# initialises and starts the background daemon.
set -eu

# 1. uv
if ! command -v uv >/dev/null 2>&1; then
    echo "MEMENTO_INSTALL_UV ,{\"status\":\"installing\"}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

# 2. memento — from this checkout if present, else from git
if [ -f "pyproject.toml" ] && grep -q "name = \"memento-memory\"" pyproject.toml 2>/dev/null; then
    SRC="."
else
    SRC="${MEMENTO_REPO:-git+https://github.com/c0mpli/memento}"
fi
echo "MEMENTO_INSTALL_TOOL ,{\"source\":\"$SRC\"}"
uv tool install --force "$SRC"

# 3. init + start
memento init
memento start
memento doctor || true

echo "MEMENTO_INSTALL_DONE ,{\"next\":\"claude mcp add memento -- memento mcp\"}"
