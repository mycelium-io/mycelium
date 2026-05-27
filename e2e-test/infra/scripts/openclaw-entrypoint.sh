#!/bin/bash
# OpenClaw gateway entrypoint for E2E CI.
#
# Reads Matrix tokens from /shared/matrix-tokens.json (written by the
# matrix-bootstrap container), configures agents based on OPENCLAW_ROLE,
# and starts the gateway.
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

ROOM_ID=$(python3 -c "import json; print(json.load(open('$TOKEN_FILE'))['room_id'])" 2>/dev/null || echo "")

get_token() {
    python3 -c "import json; print(json.load(open('$TOKEN_FILE'))['tokens']['$1'])" 2>/dev/null || echo ""
}

mkdir -p "$CONFIG_DIR"

case "$ROLE" in
    hub)
        AGENTS='["agent-alpha","agent-beta","agent-gamma","agent-delta"]'
        ;;
    spoke1)
        AGENTS='["claire-agent"]'
        ;;
    spoke2)
        AGENTS='["oclw5-agent"]'
        ;;
    *)
        echo "[openclaw-entrypoint] ERROR: Unknown role: $ROLE" >&2
        exit 1
        ;;
esac

# Build openclaw.json dynamically
AGENT_CONFIGS=""
for agent in $(echo "$AGENTS" | python3 -c "import sys,json; [print(a) for a in json.load(sys.stdin)]"); do
    TOKEN=$(get_token "$agent")
    if [ -z "$TOKEN" ]; then
        echo "[openclaw-entrypoint] WARNING: No token for $agent" >&2
        continue
    fi
    if [ -n "$AGENT_CONFIGS" ]; then
        AGENT_CONFIGS="$AGENT_CONFIGS,"
    fi
    AGENT_CONFIGS="$AGENT_CONFIGS
    {
      \"id\": \"$agent\",
      \"name\": \"$agent\",
      \"model\": \"${LLM_MODEL:-anthropic/claude-sonnet-4-20250514}\",
      \"matrixUserId\": \"@$agent:local\",
      \"matrixAccessToken\": \"$TOKEN\"
    }"
done

cat > "$CONFIG_DIR/openclaw.json" <<EOCFG
{
  "gateway": {
    "port": 3100
  },
  "channels": {
    "matrix": {
      "homeserverUrl": "$MATRIX_HOMESERVER",
      "requireMention": true,
      "rooms": ["$ROOM_ID"]
    }
  },
  "plugins": {
    "mycelium": {
      "enabled": true,
      "backendUrl": "$MYCELIUM_BACKEND_URL"
    }
  },
  "agents": [$AGENT_CONFIGS
  ]
}
EOCFG

echo "[openclaw-entrypoint] Config written to $CONFIG_DIR/openclaw.json"
echo "[openclaw-entrypoint] Starting gateway..."

exec openclaw gateway start --config "$CONFIG_DIR/openclaw.json"
