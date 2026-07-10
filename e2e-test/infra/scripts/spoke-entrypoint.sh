#!/bin/bash
# Unified spoke/hub entrypoint for E2E CI.
#
# ``OPENCLAW_ROLE`` selects the Matrix agent set when openclaw is enabled:
#   hub    → agent-alpha agent-beta agent-gamma agent-delta
#   spoke1 → claire-agent
#   spoke2 → oclw5-agent
#
# Reads ``SPOKE_ADAPTERS`` (comma-separated) and stands up the requested
# adapter runtimes side-by-side. Process supervision is delegated to
# ``supervisord`` (PID >1, tini is PID 1) — no systemd in the container.
#
# Always-on processes:
#   - mycelium metrics collect (spoke OTLP collector → hub)
#   - mycelium daemon run --foreground (mycelium-daemon, dispatches cold-spawn adapters)
#
# Conditional processes (per ``SPOKE_ADAPTERS``):
#   - openclaw: openclaw gateway run
#   - cursor:   no long-running process (cursor-agent is invoked on demand)
#   - hermes:   hermes gateway run
#
# Backwards-compat: if SPOKE_ADAPTERS is unset, defaults to "openclaw"
# (matches the previous behaviour of the openclaw-only spoke image).

set -euo pipefail

# When the container starts as root (compose spoke image), install host secrets
# with spoke ownership, run bootstrap as spoke, then start supervisord as root
# (root supervisord can spawn spoke-owned programs and wire stdout to fd 1).
SPOKE_HOME="/home/spoke"
install_cursor_auth() {
    local src=/run/host-secrets/cursor-auth.json
    local dst="${SPOKE_HOME}/.config/cursor/auth.json"
    if [ ! -s "$src" ]; then
        return 0
    fi
    install -d -o spoke -g spoke -m 700 "${SPOKE_HOME}/.config/cursor"
    install -o spoke -g spoke -m 600 "$src" "$dst"
    echo "[spoke-entrypoint] Installed cursor auth for spoke user"
}

start_supervisord() {
    local conf="$1"
    if [ "$(id -u)" -eq 0 ]; then
        awk '/^\[program:/ { print; print "user=spoke"; next }1' "$conf" > "${conf}.root"
        mv "${conf}.root" "$conf"
    fi
    exec /usr/bin/supervisord -c "$conf"
}

if [ "$(id -u)" -eq 0 ] && [ "${SPOKE_BOOTSTRAP_CHILD:-}" != 1 ]; then
    install_cursor_auth
    if [ -d "${SPOKE_HOME}/.hermes" ]; then
        chown -R spoke:spoke "${SPOKE_HOME}/.hermes" 2>/dev/null || true
    fi
    gosu spoke env HOME="${SPOKE_HOME}" SPOKE_BOOTSTRAP_CHILD=1 "$0"
    if [ -d "${SPOKE_HOME}/.hermes" ]; then
        chown -R spoke:spoke "${SPOKE_HOME}/.hermes" 2>/dev/null || true
    fi
    start_supervisord /tmp/spoke-supervisord.conf
fi

if [ "${SPOKE_BOOTSTRAP_CHILD:-}" = 1 ]; then
    export HOME="${SPOKE_HOME}"
fi

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
    echo "[spoke-entrypoint] mycelium CLI not found — installing via uv+wheel..."
    if ! command -v uv &>/dev/null; then
        curl -fsSL https://astral.sh/uv/install.sh -o /tmp/uv-install.sh \
            && UV_INSTALL_DIR=/usr/local sh /tmp/uv-install.sh \
            && rm -f /tmp/uv-install.sh
    fi
    export PATH="/usr/local/bin:${PATH}"
    _mc_latest=$(curl -fsSL "https://api.github.com/repos/mycelium-io/mycelium/releases/latest" | jq -r '.tag_name')
    _mc_ver="${_mc_latest#v}"
    curl -fsSL \
        "https://github.com/mycelium-io/mycelium/releases/download/${_mc_latest}/mycelium_cli-${_mc_ver}-py3-none-any.whl" \
        -o "/tmp/mycelium_cli-${_mc_ver}-py3-none-any.whl"
    UV_TOOL_DIR=/usr/local/share/uv/tools \
        UV_PYTHON_INSTALL_DIR=/usr/local/share/uv/python \
        uv tool install "/tmp/mycelium_cli-${_mc_ver}-py3-none-any.whl" --python 3.12 --force 2>&1 | sed 's/^/  /'
    rm -f "/tmp/mycelium_cli-${_mc_ver}-py3-none-any.whl"
    ln -sf /usr/local/share/uv/tools/mycelium-cli/bin/mycelium /usr/local/bin/mycelium 2>/dev/null || true
fi
echo "[spoke-entrypoint] mycelium CLI:     $(mycelium --version 2>/dev/null || echo 'installed')"
/openclaw/patch-mycelium-daemon.sh 2>&1 \
    || echo "[spoke-entrypoint] mycelium daemon patch skipped"

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

# CFN workspace + default MAS (written by mycelium-bootstrap to the shared volume).
MYCELIUM_CONFIG_FILE="${MYCELIUM_CONFIG_FILE:-/shared/mycelium-config.json}"
if [ -f "$MYCELIUM_CONFIG_FILE" ]; then
    eval "$(node -e "
      const c = JSON.parse(require('fs').readFileSync(process.argv[1], 'utf8'));
      if (c.workspace_id) process.stdout.write('export BOOTSTRAP_WORKSPACE_ID=' + JSON.stringify(c.workspace_id) + '\n');
      if (c.mas_id) process.stdout.write('export BOOTSTRAP_MAS_ID=' + JSON.stringify(c.mas_id) + '\n');
    " "$MYCELIUM_CONFIG_FILE")"
    if [ -n "${BOOTSTRAP_WORKSPACE_ID:-}" ]; then
        mycelium config set server.workspace_id "$BOOTSTRAP_WORKSPACE_ID" 2>/dev/null || true
        echo "[spoke-entrypoint] workspace_id from bootstrap: $BOOTSTRAP_WORKSPACE_ID"
    fi
    if [ -n "${BOOTSTRAP_MAS_ID:-}" ]; then
        mycelium config set server.mas_id "$BOOTSTRAP_MAS_ID" 2>/dev/null || true
        echo "[spoke-entrypoint] mas_id from bootstrap: $BOOTSTRAP_MAS_ID"
    fi
fi
# Env overrides (compose CI exports these after bootstrap).
[ -n "${WORKSPACE_ID:-}" ] && mycelium config set server.workspace_id "$WORKSPACE_ID" 2>/dev/null || true
[ -n "${MAS_ID:-}" ] && mycelium config set server.mas_id "$MAS_ID" 2>/dev/null || true

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
        hub)
            AGENTS="agent-alpha agent-beta agent-gamma agent-delta"
            ;;
        spoke1) AGENTS="claire-agent" ;;
        spoke2) AGENTS="oclw5-agent" ;;
        *)
            echo "[spoke-entrypoint] ERROR: Unknown role: $ROLE (expected hub, spoke1, or spoke2)" >&2
            exit 1
            ;;
    esac

    # Install the mycelium OpenClaw plugin before generating openclaw.json so
    # extensions/mycelium exists and the mycelium-room channel can be enabled.
    mycelium adapter add openclaw --yes 2>&1 \
        || echo "[spoke-entrypoint] adapter add openclaw skipped (trying infra plugin install)"
    /openclaw/install-openclaw-mycelium-plugin.sh 2>&1 \
        || echo "[spoke-entrypoint] infra mycelium plugin install skipped"

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

      const path = require('path');
      const configDir = '$CONFIG_DIR';
      const hasMycelium = fs.existsSync(path.join(configDir, 'extensions', 'mycelium'));
      if (!hasMycelium) {
        console.log('[spoke-entrypoint] Mycelium plugin not installed yet — omitting mycelium-room channel');
      }

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
          ...(hasMycelium ? {
            'mycelium-room': {
              enabled: true,
              backendUrl: '${MYCELIUM_BACKEND_URL:-http://mycelium-backend:8000}',
              requireMention: false,
              room: 'mycelium_room',
              agents: validAgents
            }
          } : {})
        },
        plugins: {
          allow: hasMycelium ? ['litellm', 'matrix', 'mycelium'] : ['litellm', 'matrix'],
          entries: {
            matrix: { enabled: true },
            litellm: { enabled: true },
            ...(hasMycelium ? { mycelium: { enabled: true } } : {})
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

    mycelium adapter add openclaw --step=otel --yes 2>&1 \
        || echo "[spoke-entrypoint] openclaw otel step skipped"
    /openclaw/install-openclaw-skills.sh 2>&1 \
        || echo "[spoke-entrypoint] openclaw skill install skipped"
    /openclaw/patch-openclaw-plugin.sh 2>&1 \
        || echo "[spoke-entrypoint] openclaw plugin patch skipped"
fi

# ── Cursor bootstrap (if enabled) ───────────────────────────────────

if has_adapter cursor; then
    CURSOR_MODEL="${CURSOR_MODEL:-claude-4.5-haiku}"
    echo "[spoke-entrypoint] Bootstrapping cursor..."
    if ! command -v cursor-agent &>/dev/null; then
        echo "[spoke-entrypoint] ERROR: cursor-agent binary missing from image" >&2
        exit 1
    fi
    if [ ! -r "$HOME/.config/cursor/auth.json" ] && [ -z "${CURSOR_API_KEY:-}" ]; then
        echo "[spoke-entrypoint] WARNING: no cursor auth.json and CURSOR_API_KEY unset; cursor tests will fail"
    fi
    if [ -n "${CURSOR_API_KEY:-}" ]; then
        echo "[spoke-entrypoint] Cursor auth: CURSOR_API_KEY (headless)"
    elif [ -r "$HOME/.config/cursor/auth.json" ]; then
        echo "[spoke-entrypoint] Cursor auth: ~/.config/cursor/auth.json"
    fi
    if [ -n "${CURSOR_MODEL:-}" ]; then
        echo "[spoke-entrypoint] Cursor model: $CURSOR_MODEL"
    fi
    mycelium adapter add cursor --yes 2>&1 \
        || echo "[spoke-entrypoint] adapter add cursor skipped"
fi

# ── Hermes bootstrap (if enabled) ───────────────────────────────────

if has_adapter hermes; then
    echo "[spoke-entrypoint] Bootstrapping hermes..."
    if [ -d "$HERMES_DIR" ] && [ ! -w "$HERMES_DIR" ]; then
        if command -v gosu >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
            echo "[spoke-entrypoint] Fixing root-owned ${HERMES_DIR}"
            gosu root chown -R spoke:spoke "$HERMES_DIR"
        fi
    fi
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
        [ -n "${LLM_BASE_URL:-}" ] && echo "LLM_BASE_URL=$LLM_BASE_URL"
        [ -n "${LLM_MODEL:-}" ]    && echo "LLM_MODEL=$LLM_MODEL"
        echo "GATEWAY_ALLOW_ALL_USERS=true"
    } > "$HERMES_DIR/.env"

    mycelium adapter add hermes --yes 2>&1 \
        || echo "[spoke-entrypoint] adapter add hermes skipped"
    /openclaw/patch-hermes-plugin.sh 2>&1 \
        || echo "[spoke-entrypoint] hermes plugin patch skipped"

    # Route Hermes inference through the same LiteLLM proxy as OpenClaw.
    # Hermes custom-provider mode reads model.{api_key,base_url,default} from
    # config.yaml — not auth.json / OPENROUTER credential pool.
    if [ -n "${LLM_API_KEY:-}" ]; then
        HERMES_MODEL="${LLM_MODEL:-anthropic/claude-sonnet-4-20250514}"
        case "$HERMES_MODEL" in
            openai/*) HERMES_MODEL="${HERMES_MODEL#openai/}" ;;
        esac
        HERMES_LITELLM_BASE="${LLM_BASE_URL:-}"
        HERMES_LITELLM_BASE="${HERMES_LITELLM_BASE%/}"
        if [ -n "$HERMES_LITELLM_BASE" ] && [ "${HERMES_LITELLM_BASE##*/}" != "v1" ]; then
            HERMES_LITELLM_BASE="${HERMES_LITELLM_BASE}/v1"
        fi
        _hermes_cfg() {
            HOME="$HOME" HERMES_HOME="$HERMES_DIR" hermes config set "$@" 2>/dev/null \
                || echo "[spoke-entrypoint] hermes config set $1 skipped"
        }
        _hermes_cfg model.provider custom
        _hermes_cfg model.api_mode chat_completions
        _hermes_cfg model.api_key "$LLM_API_KEY"
        _hermes_cfg model.default "$HERMES_MODEL"
        if [ -n "$HERMES_LITELLM_BASE" ]; then
            _hermes_cfg model.base_url "$HERMES_LITELLM_BASE"
            echo "[spoke-entrypoint] Hermes model → $HERMES_MODEL via $HERMES_LITELLM_BASE"
        else
            echo "[spoke-entrypoint] Hermes model → $HERMES_MODEL (no LLM_BASE_URL)"
        fi
    fi
fi

# ── Build supervisord.conf ──────────────────────────────────────────
#
# Always-on programs: collector + mycelium-daemon.
# Per-adapter programs added conditionally.

SUPERVISOR_CONF="/tmp/spoke-supervisord.conf"

# Supervisord may run as root (compose image) while programs run as spoke.
# Always pin HOME so mycelium/openclaw do not read /root/.mycelium or /root/.openclaw.
SPOKE_PROG_ENV='directory=/home/spoke
environment=HOME="/home/spoke",HERMES_HOME="/home/spoke/.hermes",PATH="/usr/local/bin:/usr/local/share/uv/tools/mycelium-cli/bin:/home/spoke/.local/bin:%(ENV_PATH)s"'

# Hermes gateway LLM creds live in config.yaml (model.api_key); keep env for aux tools.
HERMES_PROG_ENV="$SPOKE_PROG_ENV"
if has_adapter hermes && [ -n "${LLM_API_KEY:-}" ]; then
    HERMES_PROG_ENV='directory=/home/spoke
environment=HOME="/home/spoke",HERMES_HOME="/home/spoke/.hermes",PATH="/usr/local/bin:/usr/local/share/uv/tools/mycelium-cli/bin:/home/spoke/.local/bin:%(ENV_PATH)s",GATEWAY_ALLOW_ALL_USERS="true"'
fi

# Cursor cold-spawn reads CURSOR_API_KEY + CURSOR_MODEL from the daemon process env.
DAEMON_PROG_ENV="$SPOKE_PROG_ENV"
if has_adapter cursor; then
    _daemon_extra=",CURSOR_MODEL=\"${CURSOR_MODEL:-claude-4.5-haiku}\""
    [ -n "${CURSOR_API_KEY:-}" ] && _daemon_extra="${_daemon_extra},CURSOR_API_KEY=\"${CURSOR_API_KEY}\""
    DAEMON_PROG_ENV='directory=/home/spoke
environment=HOME="/home/spoke",HERMES_HOME="/home/spoke/.hermes",PATH="/usr/local/bin:/usr/local/share/uv/tools/mycelium-cli/bin:/home/spoke/.local/bin:%(ENV_PATH)s"'"${_daemon_extra}"
fi

cat > "$SUPERVISOR_CONF" <<CONF
[supervisord]
nodaemon=true
logfile=/tmp/supervisord.log
loglevel=info

[program:metrics-collector]
${SPOKE_PROG_ENV}
command=mycelium metrics collect --foreground
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0

[program:mycelium-daemon]
${DAEMON_PROG_ENV}
command=mycelium daemon run --foreground
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
${SPOKE_PROG_ENV}
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
${HERMES_PROG_ENV}
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

if [ "${SPOKE_BOOTSTRAP_CHILD:-}" = 1 ]; then
    exit 0
fi

start_supervisord "$SUPERVISOR_CONF"
