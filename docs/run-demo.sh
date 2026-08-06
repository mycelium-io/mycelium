#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Launch all four demo agent simulators in parallel.
# Each runs in its own terminal-multiplexer pane or background process.
#
# Usage:
#   ./docs/run-demo.sh [room]           # default room: dissent-map-demo
#   ./docs/run-demo.sh dissent-map-demo
#
# Prerequisite: run from the repo root with the stack already up.
#   mycelium room create dissent-map-demo   (first time only)
#   mycelium session create --room dissent-map-demo

set -euo pipefail

ROOM="${1:-dissent-map-demo}"
SCRIPT="$(dirname "$0")/demo-agent.py"
LOG_DIR="/tmp/mycelium-demo-logs"

mkdir -p "$LOG_DIR"

echo "Dissent-map demo — room: $ROOM"
echo "Logs: $LOG_DIR/{persona}.log"
echo ""

PERSONAS=(sre-agent secops-agent pm-agent eng-lead)
PIDS=()

for persona in "${PERSONAS[@]}"; do
    log="$LOG_DIR/${persona}.log"
    python3 "$SCRIPT" --persona "$persona" --room "$ROOM" >"$log" 2>&1 &
    pid=$!
    PIDS+=("$pid")
    echo "  [$persona] started (PID $pid) → $log"
done

echo ""
echo "All agents running. Watch the UI at http://localhost:8080/room/$ROOM"
echo "To tail all logs:  tail -f $LOG_DIR/*.log"
echo ""
echo "Flow:"
echo "  1. Agents negotiate in session 1 — watch swim lanes in UI"
echo "  2. IMPASSE banner appears — read dissent artifact, write ruling in UI"
echo "  3. Agents detect ruling and auto-join session 2"
echo "  4. Session 2 converges — plan compiled"
echo ""

# Wait for all agents; report exit codes
failed=0
for i in "${!PIDS[@]}"; do
    pid="${PIDS[$i]}"
    persona="${PERSONAS[$i]}"
    if wait "$pid"; then
        echo "  [$persona] finished OK"
    else
        echo "  [$persona] exited with error (rc=$?) — check $LOG_DIR/${persona}.log"
        failed=1
    fi
done

exit "$failed"
