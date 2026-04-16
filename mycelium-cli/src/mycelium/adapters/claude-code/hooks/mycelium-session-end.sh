#!/bin/bash
# mycelium-session-end.sh
# Claude Code hook registered for the SessionEnd event.
#
# Identical to mycelium-stop.sh in intent: one last knowledge-extract pass
# in case a turn finished without a preceding Stop event. Both exist
# because Stop fires per assistant response while SessionEnd only fires
# when the session actually ends — shipping on both keeps at-least-one
# chance of capturing the final turn. All errors are swallowed; this hook
# must not break the SessionEnd chain.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXTRACT_SCRIPT="${SCRIPT_DIR}/mycelium-knowledge-extract.py"

if [[ ! -f "$EXTRACT_SCRIPT" ]]; then
    exit 0
fi

if [[ -t 0 ]]; then
    exit 0
fi

HOOK_INPUT=$(cat || true)
if [[ -z "$HOOK_INPUT" ]]; then
    exit 0
fi

printf '%s' "$HOOK_INPUT" | python3 "$EXTRACT_SCRIPT" >/dev/null 2>&1 &

exit 0
