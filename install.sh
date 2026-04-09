#!/usr/bin/env bash
# install.sh — Deploy AgentShield hook to Hermes
# Usage: bash install.sh [--hermes-home /path/to/.hermes]
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HOOK_DIR="$HERMES_HOME/hooks/agentshield"
CONFIG_DST="$HERMES_HOME/agentshield.yaml"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Parse optional --hermes-home flag
while [[ $# -gt 0 ]]; do
  case "$1" in
    --hermes-home) HERMES_HOME="$2"; HOOK_DIR="$HERMES_HOME/hooks/agentshield"; shift 2 ;;
    *) echo "Unknown argument: $1"; exit 1 ;;
  esac
done

echo "Installing AgentShield to: $HOOK_DIR"

# 1. Create hook directory and copy files
mkdir -p "$HOOK_DIR"
cp "$REPO_DIR/hook/handler.py" "$HOOK_DIR/handler.py"
cp "$REPO_DIR/hook/HOOK.yaml"  "$HOOK_DIR/HOOK.yaml"
echo "  ✓ hook/handler.py  →  $HOOK_DIR/handler.py"
echo "  ✓ hook/HOOK.yaml   →  $HOOK_DIR/HOOK.yaml"

# 2. Copy example config if no config exists yet
if [[ ! -f "$CONFIG_DST" ]]; then
  cp "$REPO_DIR/config/agentshield.yaml.example" "$CONFIG_DST"
  echo "  ✓ Created default config: $CONFIG_DST"
  echo ""
  echo "  ⚠️  Edit $CONFIG_DST and set your owner_chat_id before starting the gateway."
else
  echo "  ℹ  Config already exists, not overwritten: $CONFIG_DST"
fi

# 3. Verify PyYAML is available (required by handler.py)
if ! python3 -c "import yaml" 2>/dev/null; then
  echo ""
  echo "  ⚠️  PyYAML not found. Installing..."
  pip install pyyaml --quiet
  echo "  ✓ PyYAML installed"
fi

echo ""
echo "✅ AgentShield installed. Restart the Hermes gateway to activate:"
echo "   hermes gateway restart"
echo ""
echo "Admin commands (send from your owner Telegram account):"
echo "   /as_assign <chat_id> <role>   — assign a role"
echo "   /as_revoke <chat_id>          — remove assignment"
echo "   /as_roles                     — list all assignments"
echo "   /as_info <chat_id>            — show role + rate state"
