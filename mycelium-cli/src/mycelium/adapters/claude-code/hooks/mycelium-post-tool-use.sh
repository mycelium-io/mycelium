#!/bin/bash
# mycelium-post-tool-use.sh
# Claude Code hook: fires after tool use (Write, Edit, Bash, Task).
# Captures tool activity into a JSONL batch file and flushes when full.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FLUSH_SCRIPT="${SCRIPT_DIR}/../scripts/flush-batch.sh"

# ---------------------------------------------------------------------------
# Inputs (passed by Claude Code as env vars or positional args)
# ---------------------------------------------------------------------------
TOOL_NAME="${CLAUDE_CODE_TOOL_NAME:-${1:-unknown}}"
TOOL_SUMMARY="${CLAUDE_CODE_TOOL_SUMMARY:-${2:-}}"
SESSION_ID="${MYCELIUM_SESSION_ID:-${CLAUDE_CODE_SESSION_ID:-default}}"
AGENT_HANDLE="${MYCELIUM_AGENT_HANDLE:-unknown}"

BATCH_FILE="/tmp/mycelium-batch-${SESSION_ID}.jsonl"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# ---------------------------------------------------------------------------
# Truncate summary to keep batch entries reasonably sized
# ---------------------------------------------------------------------------
MAX_SUMMARY_LEN=500
if [[ ${#TOOL_SUMMARY} -gt $MAX_SUMMARY_LEN ]]; then
    TOOL_SUMMARY="${TOOL_SUMMARY:0:$MAX_SUMMARY_LEN}..."
fi

# Escape special JSON characters in the summary
TOOL_SUMMARY_ESCAPED=$(printf '%s' "$TOOL_SUMMARY" | sed 's/\\/\\\\/g; s/"/\\"/g; s/\t/\\t/g' | tr '\n' ' ')

# ---------------------------------------------------------------------------
# Append entry to batch file
# ---------------------------------------------------------------------------
cat >> "$BATCH_FILE" <<ENDJSON
{"tool": "${TOOL_NAME}", "summary": "${TOOL_SUMMARY_ESCAPED}", "agent": "${AGENT_HANDLE}", "timestamp": "${TIMESTAMP}", "session_id": "${SESSION_ID}"}
ENDJSON

# ---------------------------------------------------------------------------
# Flush if batch has reached 10 items
# ---------------------------------------------------------------------------
LINE_COUNT=$(wc -l < "$BATCH_FILE" | tr -d ' ')
if [[ "$LINE_COUNT" -ge 10 ]]; then
    "$FLUSH_SCRIPT" "$BATCH_FILE" 2>/dev/null &
fi
