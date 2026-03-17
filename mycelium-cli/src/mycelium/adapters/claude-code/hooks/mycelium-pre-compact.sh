#!/bin/bash
# mycelium-pre-compact.sh
# Claude Code hook: fires before context compaction.
# Flushes any remaining batch items to the mycelium memory API so they
# are persisted before the context window is compacted.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUSH_SCRIPT="${SCRIPT_DIR}/../scripts/flush-batch.sh"

SESSION_ID="${MYCELIUM_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-default}}"
BATCH_FILE="/tmp/mycelium-batch-${SESSION_ID}.jsonl"

# ---------------------------------------------------------------------------
# Flush remaining items (if any)
# ---------------------------------------------------------------------------
if [[ -f "$BATCH_FILE" ]] && [[ -s "$BATCH_FILE" ]]; then
    echo "[mycelium] Pre-compact: flushing remaining batch items..." >&2
    "$FLUSH_SCRIPT" "$BATCH_FILE" 2>/dev/null || true
fi
