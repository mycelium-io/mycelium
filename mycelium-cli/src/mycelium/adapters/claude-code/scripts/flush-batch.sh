#!/bin/bash
# flush-batch.sh
# Reads a JSONL batch file of tool-use events and writes a single aggregated
# memory to the mycelium memory API. One memory per flush keeps the room
# free of per-tool key spam while still preserving the activity log.
#
# The destination endpoint is POST /rooms/{room}/memory, which expects the
# MemoryBatchCreate shape:
#   {
#     "items": [
#       {
#         "key":        "log/tool-use/{session}/{timestamp}",
#         "value":      { ... the batched tool entries ... },
#         "created_by": "<agent-handle>"
#       }
#     ]
#   }
#
# Usage: ./flush-batch.sh <batch_file_path>

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_SCRIPT="${SCRIPT_DIR}/mycelium-api.sh"

BATCH_FILE="${1:?Usage: flush-batch.sh <batch_file_path>}"

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

MYCELIUM_ROOM="${MYCELIUM_ROOM:-$(read_toml_value "active")}"
MYCELIUM_AGENT_HANDLE="${MYCELIUM_AGENT_HANDLE:-$(read_toml_value "name")}"
MYCELIUM_AGENT_HANDLE="${MYCELIUM_AGENT_HANDLE:-claude-code}"

if [[ -z "$MYCELIUM_ROOM" ]]; then
    echo "[mycelium] No room configured; skipping batch flush." >&2
    exit 0
fi

# ---------------------------------------------------------------------------
# Guard: nothing to flush
# ---------------------------------------------------------------------------
if [[ ! -f "$BATCH_FILE" ]] || [[ ! -s "$BATCH_FILE" ]]; then
    exit 0
fi

# ---------------------------------------------------------------------------
# Use a lock file to prevent concurrent flushes
# ---------------------------------------------------------------------------
LOCK_FILE="${BATCH_FILE}.lock"
exec 200>"$LOCK_FILE"
flock -n 200 || { echo "[mycelium] Flush already in progress, skipping." >&2; exit 0; }

# ---------------------------------------------------------------------------
# Read items and build a JSON array of the batched tool events
# ---------------------------------------------------------------------------
ITEMS="["
FIRST=true
while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if $FIRST; then
        ITEMS+="$line"
        FIRST=false
    else
        ITEMS+=",$line"
    fi
done < "$BATCH_FILE"
ITEMS+="]"

ITEM_COUNT=$(wc -l < "$BATCH_FILE" | tr -d ' ')
SESSION_ID="${MYCELIUM_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-default}}"
TIMESTAMP="$(date -u +"%Y%m%dT%H%M%SZ")"
KEY="log/tool-use/${SESSION_ID}/${TIMESTAMP}"

# ---------------------------------------------------------------------------
# POST a single memory item containing the whole batch as its value.
# Matches the MemoryBatchCreate schema on the backend.
# ---------------------------------------------------------------------------
BODY=$(cat <<ENDJSON
{
    "items": [
        {
            "key": "${KEY}",
            "value": {
                "session_id": "${SESSION_ID}",
                "type": "tool_activity",
                "item_count": ${ITEM_COUNT},
                "items": ${ITEMS}
            },
            "tags": ["claude-code", "tool-activity"],
            "created_by": "${MYCELIUM_AGENT_HANDLE}"
        }
    ]
}
ENDJSON
)

RESPONSE=$("$API_SCRIPT" POST "rooms/${MYCELIUM_ROOM}/memory" "$BODY" 2>&1) || true

if [[ -n "$RESPONSE" ]]; then
    echo "[mycelium] Flushed batch (${ITEM_COUNT} items) to ${MYCELIUM_ROOM}/${KEY}" >&2
fi

# ---------------------------------------------------------------------------
# Truncate the batch file after successful flush
# ---------------------------------------------------------------------------
: > "$BATCH_FILE"

# Release lock
exec 200>&-
rm -f "$LOCK_FILE"
