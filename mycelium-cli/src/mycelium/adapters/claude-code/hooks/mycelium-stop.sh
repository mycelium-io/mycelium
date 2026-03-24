#!/bin/bash
# mycelium-stop.sh
# Claude Code hook: fires when Claude finishes responding.
# Syncs any local .mycelium/ changes to the git remote.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYNC_SCRIPT="${SCRIPT_DIR}/mycelium-sync.sh"

if [[ -x "$SYNC_SCRIPT" ]]; then
    "$SYNC_SCRIPT" push-pull "mycelium: auto-sync on stop" 2>/dev/null &
fi
