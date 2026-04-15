#!/bin/bash
# mycelium-session-end.sh
# Claude Code hook: fires on session end.
# Flushes the tool-activity batch, syncs room files, cleans up temp files.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUSH_SCRIPT="${SCRIPT_DIR}/../scripts/flush-batch.sh"
EXTRACT_SCRIPT="${SCRIPT_DIR}/mycelium-knowledge-extract.py"

# ---------------------------------------------------------------------------
# Read stdin hook input once so we can feed it to the knowledge-extract
# script without losing it on the pipe.
# ---------------------------------------------------------------------------
HOOK_INPUT=""
if [[ ! -t 0 ]]; then
    HOOK_INPUT=$(cat || true)
fi

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
# Final knowledge extract pass — catches anything the Stop hook may have
# missed (e.g. last turn still in-flight when Stop fired). Runs in the
# background so session teardown isn't blocked on the HTTP round-trip.
# ---------------------------------------------------------------------------
if [[ -n "$HOOK_INPUT" ]] && [[ -f "$EXTRACT_SCRIPT" ]]; then
    printf '%s' "$HOOK_INPUT" | python3 "$EXTRACT_SCRIPT" >/dev/null 2>&1 &
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
