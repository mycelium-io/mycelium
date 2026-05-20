#!/usr/bin/env bash
# run-decide-timing-batch.sh
#
# Batch runner used during the CFN /decide latency investigation.
# - N iterations × tests test_40 through test_46
# - Probes Postgres connection count before each iteration; aborts if
#   above CONN_GATE (mitigates the SSE-subscription leak,
#   mycelium-io/mycelium#175, while it remains unfixed)
# - Restarts openclaw-gateway locally and on a configurable list of
#   remote hosts between iterations
#
# Required environment (defaults assume the dev-box layout; override
# anywhere the layout differs):
#
#   PYTEST            path to pytest (defaults to ./.venv/bin/pytest)
#   TEST_FILE         pytest target (defaults to tests/test_mycelium_e2e.py)
#   WORKDIR           directory to cd into before invoking pytest
#                     (defaults to the repo root containing this script)
#   LOG_DIR           directory for batch logs
#   ITERS             iteration count (default 3)
#   CONN_GATE         Postgres connection count above which an iteration
#                     is skipped (default 250)
#   GATEWAY_HOSTS     space-separated list of remote hosts to restart
#                     openclaw-gateway on; local restart always runs
#
# Usage:
#   scripts/run-decide-timing-batch.sh

set -u

TESTS=(
  test_40_distributed_two_agent
  test_41_distributed_three_agent
  test_42_distributed_architecture
  test_43_distributed_resource_allocation
  test_44_distributed_asymmetric_stakes
  test_45_distributed_preexisting_context
  test_46_distributed_feature_prioritization
)

ITERS="${ITERS:-3}"
CONN_GATE="${CONN_GATE:-250}"
PYTEST="${PYTEST:-$(pwd)/.venv/bin/pytest}"
TEST_FILE="${TEST_FILE:-tests/test_mycelium_e2e.py}"
WORKDIR="${WORKDIR:-$(cd "$(dirname "$0")/.." && pwd)}"
LOG_DIR="${LOG_DIR:-$HOME/.mycelium/e2e-logs}"
GATEWAY_HOSTS="${GATEWAY_HOSTS:-oclw3 oclw5}"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/decide_timing_batch_$(date +%Y%m%d_%H%M%S).log"

cd "$WORKDIR" || exit 2

probe_pg() {
  docker exec mycelium-db psql -U postgres -tAc \
    "SELECT count(*) FROM pg_stat_activity WHERE datname='mycelium';" 2>/dev/null \
    | tr -d '[:space:]'
}

restart_gateways() {
  echo "  [gw] restarting local + remote openclaw-gateway..."
  systemctl --user restart openclaw-gateway 2>&1 | sed 's/^/    local: /'
  for h in $GATEWAY_HOSTS; do
    ssh -o StrictHostKeyChecking=no "$h" \
      "systemctl --user restart openclaw-gateway" 2>&1 | sed "s/^/    $h: /"
  done
  sleep 5
}

{
echo "=== batch start $(date -Is) ==="
echo "iters=$ITERS tests=${#TESTS[@]} conn_gate=$CONN_GATE"
echo "workdir=$WORKDIR pytest=$PYTEST"
echo

SKIPPED_ITERS=()

for iter in $(seq 1 $ITERS); do
  echo "==================================================================="
  echo "ITER $iter / $ITERS  ($(date -Is))"
  echo "==================================================================="
  restart_gateways
  conn=$(probe_pg)
  echo "  [pg] mycelium connections after restart: ${conn:-?}"
  if [[ "$conn" =~ ^[0-9]+$ ]] && [ "$conn" -gt "$CONN_GATE" ]; then
    echo "  [ABORT] connection count $conn exceeds gate $CONN_GATE — skipping iter $iter"
    SKIPPED_ITERS+=("$iter")
    continue
  fi

  for t in "${TESTS[@]}"; do
    echo
    echo "--- iter $iter :: $t :: $(date +%H:%M:%S) ---"
    pre=$(probe_pg)
    "$PYTEST" "${TEST_FILE}::${t}" -v 2>&1 | tail -8
    post=$(probe_pg)
    echo "  [pg] before=$pre after=$post"
  done
done

echo
echo "==================================================================="
echo "BATCH SUMMARY  $(date -Is)"
echo "==================================================================="
echo "skipped iters (gate tripped): ${SKIPPED_ITERS[*]:-none}"
echo "final mycelium connection count: $(probe_pg)"
echo "=== batch end $(date -Is) ==="
} 2>&1 | tee "$LOG"

echo
echo "Full log: $LOG"
