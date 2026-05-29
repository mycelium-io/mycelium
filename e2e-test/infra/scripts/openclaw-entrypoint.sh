#!/bin/bash
# OpenClaw gateway entrypoint for E2E CI.
#
# Reads Matrix tokens from /shared/matrix-tokens.json (written by the
# matrix-bootstrap container), configures agents based on OPENCLAW_ROLE,
# and starts the gateway.
#
# Uses node (not python) for JSON parsing to keep the Alpine image small.
set -euo pipefail

ROLE="${OPENCLAW_ROLE:-hub}"
TOKEN_FILE="${TOKEN_FILE:-/shared/matrix-tokens.json}"
CONFIG_DIR="/openclaw/config"

echo "[openclaw-entrypoint] Role: $ROLE"
echo "[openclaw-entrypoint] Waiting for token file..."

# Wait for matrix-bootstrap to write tokens (up to 120s)
for i in $(seq 1 60); do
    if [ -f "$TOKEN_FILE" ]; then
        echo "[openclaw-entrypoint] Token file found."
        break
    fi
    sleep 2
done

if [ ! -f "$TOKEN_FILE" ]; then
    echo "[openclaw-entrypoint] ERROR: Token file not found after 120s" >&2
    exit 1
fi

json_get() {
    node -e "
      const d = JSON.parse(require('fs').readFileSync('$TOKEN_FILE','utf8'));
      const v = $1;
      if (v !== undefined && v !== null) process.stdout.write(String(v));
    " 2>/dev/null || true
}

ROOM_ID=$(json_get "d.room_id")

mkdir -p "$CONFIG_DIR"

case "$ROLE" in
    hub)
        AGENTS="agent-alpha agent-beta agent-gamma agent-delta"
        ;;
    spoke1)
        AGENTS="claire-agent"
        ;;
    spoke2)
        AGENTS="oclw5-agent"
        ;;
    *)
        echo "[openclaw-entrypoint] ERROR: Unknown role: $ROLE" >&2
        exit 1
        ;;
esac

# Build the agents array for openclaw.json via node to avoid
# shell quoting issues with JSON construction.
node -e "
  const fs = require('fs');
  const tokens = JSON.parse(fs.readFileSync('$TOKEN_FILE', 'utf8')).tokens || {};
  const agents = '${AGENTS}'.split(' ').filter(Boolean);
  const model = process.env.LLM_MODEL || 'anthropic/claude-sonnet-4-20250514';
  const cfg = {
    gateway: { port: 3100 },
    channels: {
      matrix: {
        homeserverUrl: '$MATRIX_HOMESERVER',
        requireMention: true,
        rooms: ['$ROOM_ID']
      }
    },
    plugins: {
      mycelium: {
        enabled: true,
        backendUrl: '$MYCELIUM_BACKEND_URL'
      }
    },
    agents: agents
      .filter(id => {
        if (!tokens[id]) console.error('[openclaw-entrypoint] WARNING: No token for ' + id);
        return !!tokens[id];
      })
      .map(id => ({
        id,
        name: id,
        model,
        matrixUserId: '@' + id + ':local',
        matrixAccessToken: tokens[id]
      }))
  };
  fs.mkdirSync('$CONFIG_DIR', { recursive: true });
  fs.writeFileSync('$CONFIG_DIR/openclaw.json', JSON.stringify(cfg, null, 2));
  console.log('[openclaw-entrypoint] Config written to $CONFIG_DIR/openclaw.json');
  console.log('[openclaw-entrypoint] Agents: ' + cfg.agents.map(a => a.id).join(', '));
"

echo "[openclaw-entrypoint] Starting gateway..."
exec openclaw gateway start --config "$CONFIG_DIR/openclaw.json"
