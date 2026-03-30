#!/bin/bash
# mycelium-session-end.sh
# Claude Code hook: fires on session end.
# Writes a session summary memory and cleans up temp files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_SCRIPT="${SCRIPT_DIR}/../scripts/mycelium-api.sh"
FLUSH_SCRIPT="${SCRIPT_DIR}/../scripts/flush-batch.sh"

# ---------------------------------------------------------------------------
# Config
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

SESSION_ID="${MYCELIUM_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-default}}"
BATCH_FILE="/tmp/mycelium-batch-${SESSION_ID}.jsonl"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# ---------------------------------------------------------------------------
# Flush any remaining batch items before ending
# ---------------------------------------------------------------------------
if [[ -f "$BATCH_FILE" ]] && [[ -s "$BATCH_FILE" ]]; then
    "$FLUSH_SCRIPT" "$BATCH_FILE" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Write session summary memory
# ---------------------------------------------------------------------------
if [[ -n "$MYCELIUM_ROOM" ]]; then
    TOOL_COUNT=0
    if [[ -f "$BATCH_FILE" ]]; then
        TOOL_COUNT=$(wc -l < "$BATCH_FILE" 2>/dev/null | tr -d ' ')
    fi

    BODY=$(cat <<ENDJSON
{
    "session_id": "${SESSION_ID}",
    "agent_handle": "${MYCELIUM_AGENT_HANDLE}",
    "event": "session_end",
    "timestamp": "${TIMESTAMP}",
    "room": "${MYCELIUM_ROOM}",
    "tool_invocations": ${TOOL_COUNT}
}
ENDJSON
)
    "$API_SCRIPT" POST "sessions/${SESSION_ID}/end" "$BODY" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Sync room files from backend (fetch latest after session ends)
# ---------------------------------------------------------------------------
mycelium sync --no-reindex 2>/dev/null &

# ---------------------------------------------------------------------------
# Cleanup temp files
# ---------------------------------------------------------------------------
rm -f "$BATCH_FILE"
rm -f "/tmp/mycelium-batch-${SESSION_ID}.jsonl.lock"

echo "[mycelium] Session ${SESSION_ID} ended at ${TIMESTAMP}" >&2
