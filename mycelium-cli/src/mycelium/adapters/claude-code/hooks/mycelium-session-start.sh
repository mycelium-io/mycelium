#!/bin/bash
# mycelium-session-start.sh
# Claude Code hook: fires on session start.
# Registers the session with the backend and syncs room files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_SCRIPT="${SCRIPT_DIR}/../scripts/mycelium-api.sh"

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
# Register session start with the mycelium backend
# ---------------------------------------------------------------------------
if [[ -n "$MYCELIUM_ROOM" ]]; then
    BODY=$(cat <<ENDJSON
{
    "session_id": "${SESSION_ID}",
    "agent_handle": "${MYCELIUM_AGENT_HANDLE}",
    "event": "session_start",
    "timestamp": "${TIMESTAMP}",
    "room": "${MYCELIUM_ROOM}"
}
ENDJSON
)
    "$API_SCRIPT" POST "sessions/${SESSION_ID}/start" "$BODY" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Sync room files from backend (pull latest before starting work)
# ---------------------------------------------------------------------------
mycelium sync --no-reindex 2>/dev/null &

# Initialize the batch file for this session
BATCH_FILE="/tmp/mycelium-batch-${SESSION_ID}.jsonl"
: > "$BATCH_FILE"

echo "[mycelium] Session ${SESSION_ID} started at ${TIMESTAMP}" >&2
