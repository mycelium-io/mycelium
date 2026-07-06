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
CONFIG_DIR="$HOME/.openclaw"

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
  const rawModel = process.env.LLM_MODEL || 'anthropic/claude-sonnet-4-20250514';
  // Strip openai/ prefix — it's a LiteLLM routing hint the backend uses,
  // not understood by OpenClaw's native openai plugin.
  const bareModel = rawModel.startsWith('openai/') ? rawModel.slice(7) : rawModel;
  // For agent model refs, prefix with litellm/ so OpenClaw routes through
  // the litellm provider rather than its built-in openai plugin.
  const agentModel = 'litellm/' + bareModel;
  const baseUrl = process.env.LLM_BASE_URL || '';
  const apiKey = process.env.LLM_API_KEY || '';

  const validAgents = agents.filter(id => {
    if (!tokens[id]) console.error('[openclaw-entrypoint] WARNING: No token for ' + id);
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
      dmPolicy: 'open',
      allowFrom: ['*'],
      groupAllowFrom: ['*']
    };
  }

  const gatewayToken = require('crypto').randomBytes(24).toString('hex');

  const cfg = {
    gateway: {
      port: 18789,
      mode: 'local',
      bind: 'loopback',
      auth: { mode: 'token', token: gatewayToken },
      controlUi: { allowInsecureAuth: true }
    },
    models: {
      providers: {
        litellm: {
          baseUrl,
          apiKey,
          api: 'openai-completions',
          models: [
            {
              id: bareModel,
              name: bareModel.split('/').pop(),
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
      },
      'mycelium-room': {
        enabled: true,
        backendUrl: '${MYCELIUM_BACKEND_URL:-http://mycelium-backend:8000}',
        requireMention: true,
        room: 'mycelium_room',
        agents: validAgents
      }
    },
    plugins: {
      allow: ['litellm', 'matrix', 'mycelium'],
      entries: {
        matrix: { enabled: true },
        litellm: { enabled: true },
        mycelium: { enabled: true }
      }
    },
    bindings: validAgents.map(id => ({
      agentId: id,
      match: { channel: 'matrix', accountId: id }
    })),
    agents: {
      defaults: {
        model: agentModel,
        compaction: { mode: 'safeguard' }
      },
      list: validAgents.map(id => ({
        id,
        name: id,
        model: agentModel,
        workspace: '$CONFIG_DIR/workspace-' + id,
        sandbox: { mode: 'off' }
      }))
    }
  };

  fs.mkdirSync('$CONFIG_DIR', { recursive: true });
  fs.writeFileSync('$CONFIG_DIR/openclaw.json', JSON.stringify(cfg, null, 2));

  const envLines = [
    'LLM_API_KEY=' + apiKey,
    'LLM_BASE_URL=' + baseUrl,
    'LLM_MODEL=' + bareModel,
    ''
  ].join('\n');
  fs.writeFileSync('$CONFIG_DIR/gateway.systemd.env', envLines);

  console.log('[openclaw-entrypoint] Config written to $CONFIG_DIR/openclaw.json');
  console.log('[openclaw-entrypoint] Env written to $CONFIG_DIR/gateway.systemd.env');
  console.log('[openclaw-entrypoint] Agents: ' + validAgents.join(', '));
  console.log('[openclaw-entrypoint] Provider model ID: ' + bareModel);
  console.log('[openclaw-entrypoint] Agent model ref: ' + agentModel);
"

echo "[openclaw-entrypoint] Starting gateway..."
exec openclaw gateway run --force --verbose --bind lan