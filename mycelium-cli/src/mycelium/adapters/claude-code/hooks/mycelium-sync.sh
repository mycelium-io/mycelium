#!/bin/bash
# mycelium-sync.sh
# Claude Code hook helper: sync room files with git remote.
# Called by other hooks (session-end, post-tool-use) when auto_sync is enabled.
#
# Usage:
#   mycelium-sync.sh pull          # pull + reindex
#   mycelium-sync.sh push [msg]    # add + commit + push
#   mycelium-sync.sh push-pull     # push local changes, then pull remote

set -euo pipefail

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

MYCELIUM_ROOM="${MYCELIUM_ROOM:-$(read_toml_value "active")}"
MYCELIUM_AGENT_HANDLE="${MYCELIUM_AGENT_HANDLE:-$(read_toml_value "name")}"
MYCELIUM_AGENT_HANDLE="${MYCELIUM_AGENT_HANDLE:-unknown}"

if [[ -z "$MYCELIUM_ROOM" ]]; then
    exit 0  # No active room, nothing to sync
fi

ROOM_DIR="${HOME}/.mycelium/rooms/${MYCELIUM_ROOM}"

# Check if room is a git repo
if ! git -C "$ROOM_DIR" rev-parse --is-inside-work-tree &>/dev/null; then
    exit 0  # Not a git repo, nothing to sync
fi

ACTION="${1:-pull}"
COMMIT_MSG="${2:-mycelium: auto-sync by ${MYCELIUM_AGENT_HANDLE}}"

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

do_pull() {
    git -C "$ROOM_DIR" pull --ff-only 2>/dev/null || git -C "$ROOM_DIR" pull 2>/dev/null || true

    # Reindex search (best-effort, non-blocking)
    curl -s -X POST "${MYCELIUM_API_URL}/rooms/${MYCELIUM_ROOM}/reindex" \
        -H "Content-Type: application/json" \
        --max-time 10 >/dev/null 2>&1 || true
}

do_push() {
    cd "$ROOM_DIR"
    git add -A
    if ! git diff --cached --quiet 2>/dev/null; then
        git commit -m "$COMMIT_MSG" 2>/dev/null || true
        git push 2>/dev/null || true
    fi
}

case "$ACTION" in
    pull)
        do_pull
        ;;
    push)
        do_push
        ;;
    push-pull)
        do_push
        do_pull
        ;;
    *)
        echo "Usage: mycelium-sync.sh {pull|push|push-pull} [commit-msg]" >&2
        exit 1
        ;;
esac
