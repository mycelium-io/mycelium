#!/bin/bash
# mycelium-stop.sh
# Claude Code hook: fires when Claude finishes responding.
#
# Two jobs:
#   1. Sync room files from the backend. With ETag caching this is a cheap
#      no-op (304) when nothing has changed on the remote.
#   2. Extract new conversation turns from the session transcript and ship
#      them to mycelium-backend's /api/knowledge/ingest — which forwards to
#      CFN's shared-memories knowledge graph. Only runs when knowledge_ingest
#      is enabled AND workspace_id / mas_id are configured.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTRACT_SCRIPT="${SCRIPT_DIR}/mycelium-knowledge-extract.py"

# Claude Code passes hook input JSON on stdin. Read it once so we can feed
# it to the knowledge-extract hook without losing it.
HOOK_INPUT=""
if [[ ! -t 0 ]]; then
    HOOK_INPUT=$(cat || true)
fi

# 1. Background room sync (fire-and-forget)
mycelium sync --no-reindex 2>/dev/null &

# 2. Background knowledge extract (fire-and-forget, stdin re-piped)
if [[ -n "$HOOK_INPUT" ]] && [[ -f "$EXTRACT_SCRIPT" ]]; then
    printf '%s' "$HOOK_INPUT" | python3 "$EXTRACT_SCRIPT" >/dev/null 2>&1 &
fi

exit 0
