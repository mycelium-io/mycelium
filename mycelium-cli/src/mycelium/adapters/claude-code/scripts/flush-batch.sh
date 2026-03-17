#!/bin/bash
# flush-batch.sh
# Reads a JSONL batch file, converts entries into a batch memory create
# request, and POSTs to the mycelium memory API.
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
# Read items and build a JSON array
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

# ---------------------------------------------------------------------------
# POST batch to memory API
# ---------------------------------------------------------------------------
BODY=$(cat <<ENDJSON
{
    "room": "${MYCELIUM_ROOM}",
    "type": "tool_activity",
    "items": ${ITEMS}
}
ENDJSON
)

RESPONSE=$("$API_SCRIPT" POST "rooms/${MYCELIUM_ROOM}/memory" "$BODY" 2>&1) || true

if [[ -n "$RESPONSE" ]]; then
    echo "[mycelium] Flushed batch ($(wc -l < "$BATCH_FILE" | tr -d ' ') items) to room ${MYCELIUM_ROOM}" >&2
fi

# ---------------------------------------------------------------------------
# Truncate the batch file after successful flush
# ---------------------------------------------------------------------------
: > "$BATCH_FILE"

# Release lock
exec 200>&-
rm -f "$LOCK_FILE"
