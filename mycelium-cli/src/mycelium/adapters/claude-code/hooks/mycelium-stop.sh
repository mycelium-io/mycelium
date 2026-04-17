#!/bin/bash
# mycelium-stop.sh
# Claude Code hook registered for the Stop event.
#
# Forwards the hook's stdin JSON to mycelium-knowledge-extract.py as a
# background process so session teardown isn't blocked on the HTTP
# round-trip. The extractor self-gates on both [knowledge_ingest].enabled
# AND [adapters.claude-code].knowledge_extract — if either is false, this
# is a silent no-op. See mycelium-knowledge-extract.py for the full gate
# model.

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
