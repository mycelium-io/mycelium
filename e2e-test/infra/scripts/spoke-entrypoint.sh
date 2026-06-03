#!/bin/bash
# Spoke device entrypoint for E2E CI.
#
# Runs three processes:
#   1. mycelium metrics collect (spoke OTLP collector, forwards to hub)
#   2. mycelium daemon run      (cc-daemon, dispatches @handle mentions)
#   3. openclaw gateway run     (foreground, spoke role)
#
# Expects the same shared volume as the hub entrypoint for Matrix tokens.
set -euo pipefail

ROLE="${OPENCLAW_ROLE:-spoke1}"
TOKEN_FILE="${TOKEN_FILE:-/shared/matrix-tokens.json}"
CONFIG_DIR="$HOME/.openclaw"
MYCELIUM_DIR="$HOME/.mycelium"
BACKEND_URL="${MYCELIUM_BACKEND_URL:-http://mycelium-backend:8000}"
COLLECTOR_HUB="${COLLECTOR_HUB_URL:-http://mycelium-collector:4318}"

echo "[spoke-entrypoint] Role: $ROLE"
echo "[spoke-entrypoint] Backend: $BACKEND_URL"
echo "[spoke-entrypoint] Collector hub: $COLLECTOR_HUB"

# ── Ensure mycelium CLI is available ──────────────────────────────────
if ! command -v mycelium &>/dev/null; then
    echo "[spoke-entrypoint] mycelium CLI not found — installing from release..."
    curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
fi
echo "[spoke-entrypoint] mycelium CLI: $(mycelium --version 2>/dev/null || echo 'installed')"

# ── Wait for Matrix tokens ────────────────────────────────────────────
echo "[spoke-entrypoint] Waiting for token file..."
for i in $(seq 1 60); do
    [ -f "$TOKEN_FILE" ] && break
    sleep 2
done
if [ ! -f "$TOKEN_FILE" ]; then
    echo "[spoke-entrypoint] ERROR: Token file not found after 120s" >&2
    exit 1
fi
echo "[spoke-entrypoint] Token file found."

# ── Helper: read JSON fields via node ─────────────────────────────────
json_get() {
    node -e "
      const d = JSON.parse(require('fs').readFileSync('$TOKEN_FILE','utf8'));
      const v = $1;
      if (v !== undefined && v !== null) process.stdout.write(String(v));
    " 2>/dev/null || true
}

ROOM_ID=$(json_get "d.room_id")

# ── Initialize mycelium CLI ───────────────────────────────────────────
mkdir -p "$MYCELIUM_DIR"
mycelium init --api-url "$BACKEND_URL" 2>/dev/null || true

if [ ! -f "$MYCELIUM_DIR/config.toml" ]; then
    cat > "$MYCELIUM_DIR/config.toml" <<TOML
[server]
api_url = "$BACKEND_URL"
TOML
fi

mycelium config set server.api_url "$BACKEND_URL" 2>/dev/null || true
mycelium config set metrics.collector_url "$COLLECTOR_HUB" 2>/dev/null || true

# Write LLM credentials to .env for CLI commands
{
    [ -n "${LLM_API_KEY:-}" ]  && echo "LLM_API_KEY=$LLM_API_KEY"
    [ -n "${LLM_BASE_URL:-}" ] && echo "LLM_BASE_URL=$LLM_BASE_URL"
    [ -n "${LLM_MODEL:-}" ]    && echo "LLM_MODEL=$LLM_MODEL"
} > "$MYCELIUM_DIR/.env"

# ── Build openclaw.json ───────────────────────────────────────────────
case "$ROLE" in
    spoke1) AGENTS="claire-agent" ;;
    spoke2) AGENTS="oclw5-agent" ;;
    *)
        echo "[spoke-entrypoint] ERROR: Unknown spoke role: $ROLE" >&2
        exit 1
        ;;
esac

node -e "
  const fs = require('fs');
  const tokens = JSON.parse(fs.readFileSync('$TOKEN_FILE', 'utf8')).tokens || {};
  const agents = '${AGENTS}'.split(' ').filter(Boolean);
  const model = process.env.LLM_MODEL || 'anthropic/claude-sonnet-4-20250514';
  const baseUrl = process.env.LLM_BASE_URL || '';
  const apiKey = process.env.LLM_API_KEY || '';

  const validAgents = agents.filter(id => {
    if (!tokens[id]) console.error('[spoke-entrypoint] WARNING: No token for ' + id);
    return !!tokens[id];
  });

  const matrixAccounts = {};
  for (const id of validAgents) {
    matrixAccounts[id] = {
      userId: '@' + id + ':local',
      accessToken: tokens[id],
      homeserver: '$MATRIX_HOMESERVER',
      agentId: id,
      groups: { '$ROOM_ID': { requireMention: true } },
      dm: { allowFrom: ['*'] },
      allowFrom: ['*']
    };
  }

  const cfg = {
    gateway: { port: 18789, mode: 'local' },
    models: {
      providers: {
        litellm: {
          baseUrl,
          apiKey,
          api: 'openai-completions',
          models: [
            {
              id: model,
              name: model.split('/').pop(),
              reasoning: false,
              input: ['text'],
              contextWindow: 200000,
              maxTokens: 8192
            }
          ]
        }
      }
    },
    channels: {
      matrix: {
        enabled: true,
        homeserver: '$MATRIX_HOMESERVER',
        initialSyncLimit: 0,
        groupPolicy: 'open',
        accounts: matrixAccounts,
        dm: { allowFrom: ['*'] },
        groupAllowFrom: ['*'],
        network: { dangerouslyAllowPrivateNetwork: true }
      }
    },
    plugins: {
      allow: ['litellm', 'matrix'],
      entries: {
        matrix: { enabled: true },
        litellm: { enabled: true }
      }
    },
    agents: {
      defaults: {
        model,
        compaction: { mode: 'safeguard' }
      },
      list: validAgents.map(id => ({
        id,
        name: id,
        model,
        workspace: '$CONFIG_DIR/workspace-' + id
      }))
    }
  };

  fs.mkdirSync('$CONFIG_DIR', { recursive: true });
  fs.writeFileSync('$CONFIG_DIR/openclaw.json', JSON.stringify(cfg, null, 2));

  const envLines = [
    'LLM_API_KEY=' + apiKey,
    'LLM_BASE_URL=' + baseUrl,
    'LLM_MODEL=' + model,
    ''
  ].join('\n');
  fs.writeFileSync('$CONFIG_DIR/gateway.systemd.env', envLines);

  console.log('[spoke-entrypoint] Config written to $CONFIG_DIR/openclaw.json');
  console.log('[spoke-entrypoint] Agents: ' + validAgents.join(', '));
"

# ── Install adapter + OTel step ───────────────────────────────────────
mycelium adapter add openclaw --yes 2>&1 || echo "[spoke-entrypoint] adapter add skipped"
mycelium adapter add openclaw --step=otel --yes 2>&1 || echo "[spoke-entrypoint] otel step skipped"

# ── Start spoke metrics collector (background) ────────────────────────
echo "[spoke-entrypoint] Starting spoke metrics collector..."
mycelium metrics collect --foreground &
COLLECTOR_PID=$!
echo "[spoke-entrypoint] Collector PID: $COLLECTOR_PID"

# ── Start cc-daemon (background) ──────────────────────────────────────
echo "[spoke-entrypoint] Starting cc-daemon..."
mycelium daemon run &
DAEMON_PID=$!
echo "[spoke-entrypoint] Daemon PID: $DAEMON_PID"

# ── Cleanup on exit ───────────────────────────────────────────────────
cleanup() {
    echo "[spoke-entrypoint] Shutting down..."
    kill "$DAEMON_PID" "$COLLECTOR_PID" 2>/dev/null || true
    wait "$DAEMON_PID" "$COLLECTOR_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── Start OpenClaw gateway (foreground) ───────────────────────────────
echo "[spoke-entrypoint] Starting gateway..."
exec openclaw gateway run --force --verbose
