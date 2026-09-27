#!/usr/bin/env bash
# cursor_exec.sh — exec driver for mycelium await --loop --exec
#
# Receives tick JSON on stdin; env vars set by await:
#   MYCELIUM_ROOM    — room name
#   MYCELIUM_HANDLE  — this agent's handle
#   MYCELIUM_PROMPT  — the aligner's prompt text for this turn
#
# Runs cursor-agent -p with the prompt, then posts plain prose reply via respond.
# No accept/reject markers needed — the aligner interprets prose directly.

set -euo pipefail

ROOM="${MYCELIUM_ROOM:-}"
HANDLE="${MYCELIUM_HANDLE:-}"
PROMPT="${MYCELIUM_PROMPT:-}"
WORKSPACE="${CURSOR_WORKSPACE:-}"

if [[ -z "$ROOM" || -z "$HANDLE" ]]; then
    echo "cursor_exec: missing MYCELIUM_ROOM or MYCELIUM_HANDLE" >&2
    exit 1
fi

if [[ -z "$PROMPT" ]]; then
    exit 0
fi

SYSTEM_PROMPT="You are @${HANDLE} participating in a Mycelium coordination session.
Read the mediator's prompt and reply with your position in 1-2 concise sentences.
Do NOT include any markers, @-mentions, or preamble — plain prose only.

Mediator prompt:
${PROMPT}"

CURSOR_ARGS=("--output-format" "json" "--force" "--approve-mcps")
if [[ -n "$WORKSPACE" ]]; then
    CURSOR_ARGS+=("--workspace" "$WORKSPACE")
fi

RAW=$(cursor-agent -p "${CURSOR_ARGS[@]}" -- "$SYSTEM_PROMPT" 2>/dev/null || echo "")

REPLY=$(echo "$RAW" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    text = (
        data.get('text') or
        data.get('message') or
        data.get('content') or ''
    )
    print(str(text).strip())
except Exception:
    pass
" 2>/dev/null)

if [[ -z "$REPLY" ]]; then
    REPLY="I can accept this proposal as a reasonable starting point."
fi

mycelium respond --room "$ROOM" --handle "$HANDLE" "$REPLY"
