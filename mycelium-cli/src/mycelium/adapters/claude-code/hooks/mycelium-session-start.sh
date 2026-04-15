#!/bin/bash
# mycelium-session-start.sh
# Claude Code hook: fires on session start.
# Pulls latest room files from the backend and initializes the tool-activity
# batch file for this session.
#
# Note: this hook does not call /rooms/{room}/sessions to explicitly register
# the session. Agents register themselves by running `mycelium session join`
# when they want to participate in structured negotiation — the hook just
# prepares the local filesystem so the agent starts with fresh context.

set -euo pipefail

# ---------------------------------------------------------------------------
# Config resolution: env vars > ~/.mycelium/config.toml > defaults
# ---------------------------------------------------------------------------
CONFIG_FILE="${HOME}/.mycelium/config.toml"

read_toml_value() {
    local key="$1"
    if [[ -f "$CONFIG_FILE" ]]; then
        sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*\"\?\([^\"]*\)\"\?[[:space:]]*$/\1/p" "$CONFIG_FILE" | head -1
    fi
}

MYCELIUM_API_URL="${MYCELIUM_API_URL:-$(read_toml_value "api_url")}"
MYCELIUM_API_URL="${MYCELIUM_API_URL:-http://localhost:8000}"

MYCELIUM_AGENT_HANDLE="${MYCELIUM_AGENT_HANDLE:-$(read_toml_value "name")}"
MYCELIUM_AGENT_HANDLE="${MYCELIUM_AGENT_HANDLE:-unknown}"

MYCELIUM_ROOM="${MYCELIUM_ROOM:-$(read_toml_value "active")}"

# ---------------------------------------------------------------------------
# Session ID: use CLAUDE_CODE_SESSION_ID if available, else generate one
# ---------------------------------------------------------------------------
SESSION_ID="${CLAUDE_CODE_SESSION_ID:-$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || date +%s)}"
export MYCELIUM_SESSION_ID="$SESSION_ID"

TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# ---------------------------------------------------------------------------
# Sync room files from backend (pull latest before starting work)
# ---------------------------------------------------------------------------
mycelium sync --no-reindex 2>/dev/null &

# Initialize the batch file for this session
BATCH_FILE="/tmp/mycelium-batch-${SESSION_ID}.jsonl"
: > "$BATCH_FILE"

echo "[mycelium] Session ${SESSION_ID} started at ${TIMESTAMP}" >&2
