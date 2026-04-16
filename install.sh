#!/usr/bin/env bash
# install.sh — Deploy AgentShield to Hermes
# Usage: bash install.sh [--hermes-home /path/to/.hermes]
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HOOK_DIR="$HERMES_HOME/hooks/agentshield"
TUI_DIR="$HERMES_HOME/tui"
CONFIG_DST="$HERMES_HOME/agentshield.yaml"
BIN_DIR="${HOME}/.local/bin"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse optional --hermes-home flag
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hermes-home) HERMES_HOME="$2"; HOOK_DIR="$HERMES_HOME/hooks/agentshield"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "Installing AgentShield to: $HOOK_DIR"

# 1. Create hook directory and copy hook files
mkdir -p "$HOOK_DIR"
cp "$REPO_DIR/hook/handler.py" "$HOOK_DIR/handler.py"
cp "$REPO_DIR/hook/HOOK.yaml"  "$HOOK_DIR/HOOK.yaml"
echo "  ✓ hook/handler.py  →  $HOOK_DIR/handler.py"
echo "  ✓ hook/HOOK.yaml   →  $HOOK_DIR/HOOK.yaml"

# 2. Copy example config if no config exists yet
if [[ ! -f "$CONFIG_DST" ]]; then
  cp "$REPO_DIR/config/agentshield.yaml.example" "$CONFIG_DST"
  echo "  ✓ Created default config: $CONFIG_DST"
else
  echo "  ℹ  Config already exists, not overwritten: $CONFIG_DST"
fi

# 3. Verify PyYAML is available (required by handler.py and TUI)
if ! python3 -c "import yaml" 2>/dev/null; then
  echo ""
  echo "  ⚠️  PyYAML not found. Installing..."
  pip install pyyaml --quiet
  echo "  ✓ PyYAML installed"
fi

# 4. Install Textual for the TUI
if ! python3 -c "import textual" 2>/dev/null; then
  echo ""
  echo "  ⚠️  Textual not found. Installing..."
  pip install textual --quiet
  echo "  ✓ Textual installed"
fi

# 5. Copy TUI to ~/.hermes/tui/
mkdir -p "$TUI_DIR"
cp "$REPO_DIR/tui/config_tui.py" "$TUI_DIR/config_tui.py"
chmod +x "$TUI_DIR/config_tui.py"
echo "  ✓ tui/config_tui.py  →  $TUI_DIR/config_tui.py"

# 6. Create agentshield-config symlink in ~/.local/bin
mkdir -p "$BIN_DIR"
ln -sf "$TUI_DIR/config_tui.py" "$BIN_DIR/agentshield-config"
echo "  ✓ Symlink: $BIN_DIR/agentshield-config"

# 7. Ensure ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo ""
  echo "  ⚠️  Add this to your shell profile (~/.bashrc or ~/.zshrc):"
  echo "      export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo ""
echo "✅ AgentShield installed successfully."
echo ""
echo "   Configure:  agentshield-config"
echo "   Activate:   hermes gateway restart"
echo ""
echo "   Philosophy: One role. Maximum security."
echo "   Every user is a guest. No privilege escalation. No admin commands over chat."
