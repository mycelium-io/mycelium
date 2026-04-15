#!/bin/bash
# mycelium-pre-compact.sh
# Claude Code hook: fires before context compaction.
# Flushes any remaining batch items AND runs the knowledge extractor so
# finalized turns are shipped to CFN before compaction drops them from the
# active context window.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUSH_SCRIPT="${SCRIPT_DIR}/../scripts/flush-batch.sh"
EXTRACT_SCRIPT="${SCRIPT_DIR}/mycelium-knowledge-extract.py"

# Read stdin once so we can forward it to the extract hook without losing it.
HOOK_INPUT=""
if [[ ! -t 0 ]]; then
    HOOK_INPUT=$(cat || true)
fi

SESSION_ID="${MYCELIUM_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-default}}"
BATCH_FILE="/tmp/mycelium-batch-${SESSION_ID}.jsonl"

# ---------------------------------------------------------------------------
# Flush remaining items (if any)
# ---------------------------------------------------------------------------
if [[ -f "$BATCH_FILE" ]] && [[ -s "$BATCH_FILE" ]]; then
    echo "[mycelium] Pre-compact: flushing remaining batch items..." >&2
    "$FLUSH_SCRIPT" "$BATCH_FILE" 2>/dev/null || true
fi

# ---------------------------------------------------------------------------
# Knowledge extract — catches the in-progress turn too since compaction is
# about to erase it from the live context. The extractor's own state file
# prevents double-sends via backend content-hash dedupe.
# ---------------------------------------------------------------------------
if [[ -n "$HOOK_INPUT" ]] && [[ -f "$EXTRACT_SCRIPT" ]]; then
    printf '%s' "$HOOK_INPUT" | python3 "$EXTRACT_SCRIPT" >/dev/null 2>&1 &
fi
