#!/bin/bash
# Unified spoke entrypoint for E2E CI.
#
# Reads ``SPOKE_ADAPTERS`` (comma-separated) and stands up the requested
# adapter runtimes side-by-side. Process supervision is delegated to
# ``supervisord`` (PID >1, tini is PID 1) — no systemd in the container.
#
# Always-on processes:
#   - mycelium metrics collect (spoke OTLP collector → hub)
#   - mycelium daemon run      (cc-daemon, dispatches @handle mentions)
#
# Conditional processes (per ``SPOKE_ADAPTERS``):
#   - openclaw: openclaw gateway run
#   - cursor:   no long-running process (cursor-agent is invoked on demand)
#   - hermes:   hermes gateway run
#
# Backwards-compat: if SPOKE_ADAPTERS is unset, defaults to "openclaw"
# (matches the previous behaviour of the openclaw-only spoke image).

set -euo pipefail

# ── Inputs ──────────────────────────────────────────────────────────

ROLE="${OPENCLAW_ROLE:-spoke1}"
TOKEN_FILE="${TOKEN_FILE:-/shared/matrix-tokens.json}"
CONFIG_DIR="$HOME/.openclaw"
MYCELIUM_DIR="$HOME/.mycelium"
HERMES_DIR="${HERMES_HOME:-$HOME/.hermes}"
BACKEND_URL="${MYCELIUM_BACKEND_URL:-http://mycelium-backend:8000}"
COLLECTOR_HUB="${COLLECTOR_HUB_URL:-http://mycelium-collector:4318}"

# Normalize SPOKE_ADAPTERS into a bash array (lowercase, comma-separated).
IFS=',' read -ra ADAPTERS <<< "$(echo "${SPOKE_ADAPTERS:-openclaw}" | tr '[:upper:]' '[:lower:]')"

# Helper: ``has_adapter openclaw`` → exit 0 if listed, 1 otherwise.
has_adapter() {
    local needle="$1"
    for a in "${ADAPTERS[@]}"; do
        [[ "$a" == "$needle" ]] && return 0
    done
    return 1
}

echo "[spoke-entrypoint] Role:             $ROLE"
echo "[spoke-entrypoint] Adapters:         ${ADAPTERS[*]}"
echo "[spoke-entrypoint] Backend:          $BACKEND_URL"
echo "[spoke-entrypoint] Collector hub:    $COLLECTOR_HUB"

# ── Mycelium CLI available? ─────────────────────────────────────────

if ! command -v mycelium &>/dev/null; then
    echo "[spoke-entrypoint] mycelium CLI not found — installing from release..."
    curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
fi
echo "[spoke-entrypoint] mycelium CLI:     $(mycelium --version 2>/dev/null || echo 'installed')"

# ── Mycelium config (shared by all adapters) ────────────────────────

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

# LLM credentials → .env (consumed by adapter installers + CLI commands)
{
    [ -n "${LLM_API_KEY:-}" ]  && echo "LLM_API_KEY=$LLM_API_KEY"
    [ -n "${LLM_BASE_URL:-}" ] && echo "LLM_BASE_URL=$LLM_BASE_URL"
    [ -n "${LLM_MODEL:-}" ]    && echo "LLM_MODEL=$LLM_MODEL"
} > "$MYCELIUM_DIR/.env"

# ── OpenClaw bootstrap (if enabled) ─────────────────────────────────

if has_adapter openclaw; then
    echo "[spoke-entrypoint] Bootstrapping openclaw..."

    # Wait for matrix-bootstrap to drop tokens into the shared volume.
    echo "[spoke-entrypoint] Waiting for token file ($TOKEN_FILE)..."
    for i in $(seq 1 60); do
        [ -f "$TOKEN_FILE" ] && break
        sleep 2
    done
    if [ ! -f "$TOKEN_FILE" ]; then
        echo "[spoke-entrypoint] ERROR: Token file not found after 120s" >&2
        exit 1
    fi
    echo "[spoke-entrypoint] Token file found."

    # Helper: read JSON fields via node
    json_get() {
        node -e "
          const d = JSON.parse(require('fs').readFileSync('$TOKEN_FILE','utf8'));
          const v = $1;
          if (v !== undefined && v !== null) process.stdout.write(String(v));
        " 2>/dev/null || true
    }

    ROOM_ID=$(json_get "d.room_id")

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
      const rawModel = process.env.LLM_MODEL || 'anthropic/claude-sonnet-4-20250514';
      const bareModel = rawModel.startsWith('openai/') ? rawModel.slice(7) : rawModel;
      const agentModel = 'litellm/' + bareModel;
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
          }
        },
        plugins: {
          allow: ['litellm', 'matrix'],
          entries: {
            matrix: { enabled: true },
            litellm: { enabled: true }
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

      console.log('[spoke-entrypoint] OpenClaw config → $CONFIG_DIR/openclaw.json');
      console.log('[spoke-entrypoint] OpenClaw agents: ' + validAgents.join(', '));
    "

    mycelium adapter add openclaw --yes 2>&1 \
        || echo "[spoke-entrypoint] adapter add openclaw skipped"
    mycelium adapter add openclaw --step=otel --yes 2>&1 \
        || echo "[spoke-entrypoint] openclaw otel step skipped"
fi

# ── Cursor bootstrap (if enabled) ───────────────────────────────────

if has_adapter cursor; then
    echo "[spoke-entrypoint] Bootstrapping cursor..."
    if ! command -v cursor-agent &>/dev/null; then
        echo "[spoke-entrypoint] ERROR: cursor-agent binary missing from image" >&2
        exit 1
    fi
    # The cursor-agent auth file is expected to be mounted at
    # ~/.config/cursor/auth.json by the compose stack. If it's not
    # present we log a warning but keep going — tests that need cursor
    # will fail with a clearer error from the provisioner.
    if [ ! -f "$HOME/.config/cursor/auth.json" ]; then
        echo "[spoke-entrypoint] WARNING: cursor auth.json not mounted; cursor tests will fail"
    fi
    mycelium adapter add cursor --yes 2>&1 \
        || echo "[spoke-entrypoint] adapter add cursor skipped"
fi

# ── Hermes bootstrap (if enabled) ───────────────────────────────────

if has_adapter hermes; then
    echo "[spoke-entrypoint] Bootstrapping hermes..."
    mkdir -p "$HERMES_DIR"

    # First-run config: hermes itself writes ~/.hermes/config.yaml on
    # ``hermes setup``; we write a minimal stub so ``mycelium adapter
    # add hermes`` has something to patch.
    if [ ! -f "$HERMES_DIR/config.yaml" ]; then
        cat > "$HERMES_DIR/config.yaml" <<YAML
plugins:
  enabled: []
platforms: {}
gateway:
  port: 9119
YAML
    fi

    # LLM credentials for hermes (provider-specific env vars).
    {
        [ -n "${LLM_API_KEY:-}" ]  && echo "OPENROUTER_API_KEY=$LLM_API_KEY"
        [ -n "${LLM_API_KEY:-}" ]  && echo "ANTHROPIC_API_KEY=$LLM_API_KEY"
    } > "$HERMES_DIR/.env"

    mycelium adapter add hermes --yes 2>&1 \
        || echo "[spoke-entrypoint] adapter add hermes skipped"
fi

# ── Build supervisord.conf ──────────────────────────────────────────
#
# Always-on programs: collector + cc-daemon.
# Per-adapter programs added conditionally.

SUPERVISOR_CONF="/tmp/spoke-supervisord.conf"

cat > "$SUPERVISOR_CONF" <<CONF
[supervisord]
nodaemon=true
logfile=/tmp/supervisord.log
loglevel=info
user=spoke

[program:metrics-collector]
command=mycelium metrics collect --foreground
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:cc-daemon]
command=mycelium daemon run
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
CONF

if has_adapter openclaw; then
    cat >> "$SUPERVISOR_CONF" <<CONF

[program:openclaw-gateway]
command=openclaw gateway run --force --verbose --bind lan
autostart=true
autorestart=true
startsecs=10
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
CONF
fi

if has_adapter hermes; then
    cat >> "$SUPERVISOR_CONF" <<CONF

[program:hermes-gateway]
command=hermes gateway run
autostart=true
autorestart=true
startsecs=10
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
CONF
fi

echo "[spoke-entrypoint] supervisord config:"
echo "------"
cat "$SUPERVISOR_CONF"
echo "------"
echo "[spoke-entrypoint] Starting supervisord..."

exec /usr/bin/supervisord -c "$SUPERVISOR_CONF"
