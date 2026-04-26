#!/usr/bin/env bash
# apply-cfn-decide-timing.sh
#
# Applies experimental CFN /decide instrumentation patches to a running
# CFN container without rebuilding upstream IOC images.  Uses `docker cp`
# + `docker restart`; idempotent and reverts cleanly on container
# recreate (`mycelium up --rebuild`).
#
# Companion PRs (the "stable" form of these patches):
#   - cisco-eti/ioc-cognition-fabric-node-svc#38   (Sites 1, 3, 5, 6)
#   - outshift-open/ioc-cfn-cognition-engines#13   (Site 2)
#   - mycelium-io/mycelium#177                     (Site 4, capture)
#
# This script targets the experiment workflow where you keep working-tree
# edits in local checkouts of those repos and want to iterate without
# pushing/rebuilding.  Adapt for further experiments on:
#
#   - PR E (executor bump):  add a third docker cp for src/app/main.py
#   - PR E v2 (loop wedge):  add a docker cp for the engines wedger files
#                            (evidence/single_entity.py, concept_repo, etc)
#
# Required environment (defaults assume the dev-box layout; override
# anywhere the layout differs):
#
#   CFN_SVC_REPO     local checkout of ioc-cognition-fabric-node-svc
#   ENGINES_REPO     local checkout of ioc-cfn-cognition-engines
#   COMPOSE_DIR      directory containing the mycelium docker compose
#                    that owns mycelium-backend
#   CFN_CONTAINER    running CFN container name
#   CFN_HEALTH_PORT  port exposed inside the container for health probe
#                    (defaults to 9002 / openapi.json)
#
# Usage:
#   scripts/apply-cfn-decide-timing.sh                # apply
#   scripts/apply-cfn-decide-timing.sh --revert       # restart CFN with image defaults
#   scripts/apply-cfn-decide-timing.sh --skip-backend # don't rebuild mycelium-backend

set -euo pipefail

CFN_SVC_REPO="${CFN_SVC_REPO:-$HOME/ioc-cognition-fabric-node-svc}"
ENGINES_REPO="${ENGINES_REPO:-$HOME/ioc-cfn-cognition-engines}"
COMPOSE_DIR="${COMPOSE_DIR:-$HOME/.mycelium/docker}"
CFN_CONTAINER="${CFN_CONTAINER:-ioc-cognition-fabric-node-svc}"
CFN_HEALTH_PORT="${CFN_HEALTH_PORT:-9002}"

SITE1_SRC="${CFN_SVC_REPO}/src/app/api/semantic_nego.py"
SITE1_DST="/app/src/app/api/semantic_nego.py"
SITE2_SRC="${ENGINES_REPO}/semantic_negotiation/app/agent/semantic_negotiation.py"
SITE2_DST="/opt/venv/lib/python3.11/site-packages/semantic_negotiation/app/agent/semantic_negotiation.py"

REVERT=0
SKIP_BACKEND=0
for arg in "$@"; do
    case "$arg" in
        --revert)       REVERT=1 ;;
        --skip-backend) SKIP_BACKEND=1 ;;
        *) echo "Unknown arg: $arg" >&2; exit 2 ;;
    esac
done

log() { printf '\033[1;36m[apply-timing]\033[0m %s\n' "$*"; }
err() { printf '\033[1;31m[apply-timing]\033[0m %s\n' "$*" >&2; }

if pgrep -f "pytest .*test_4[0-6]" >/dev/null 2>&1; then
    err "pytest is running (test_4*).  Refusing to disturb the CFN container."
    err "Wait for the batch to finish, then re-run."
    exit 3
fi

if [[ "$REVERT" == "1" ]]; then
    log "Reverting: restarting $CFN_CONTAINER with image defaults"
    docker restart "$CFN_CONTAINER"
    log "CFN reverted.  Mycelium backend NOT rebuilt; capture is tolerant of missing _timing."
    exit 0
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CFN_CONTAINER"; then
    err "$CFN_CONTAINER is not running.  Run 'mycelium up' first."
    exit 4
fi
for f in "$SITE1_SRC" "$SITE2_SRC"; do
    [[ -f "$f" ]] || { err "Patch source missing: $f"; exit 5; }
done
python3 -c "import ast; ast.parse(open('$SITE1_SRC').read())" || { err "Site 1 syntax error"; exit 6; }
python3 -c "import ast; ast.parse(open('$SITE2_SRC').read())" || { err "Site 2 syntax error"; exit 6; }

log "Site 1: $SITE1_SRC  →  $CFN_CONTAINER:$SITE1_DST"
docker cp "$SITE1_SRC" "$CFN_CONTAINER:$SITE1_DST"

log "Site 2: $SITE2_SRC  →  $CFN_CONTAINER:$SITE2_DST"
docker cp "$SITE2_SRC" "$CFN_CONTAINER:$SITE2_DST"

# Drop bytecode so the new sources are loaded (uvicorn isn't in --reload).
docker exec "$CFN_CONTAINER" find /app /opt/venv/lib/python3.11/site-packages/semantic_negotiation \
    -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

log "Restarting $CFN_CONTAINER"
docker restart "$CFN_CONTAINER" >/dev/null

log "Waiting for CFN to come back up"
for i in {1..30}; do
    if docker exec "$CFN_CONTAINER" python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:${CFN_HEALTH_PORT}/openapi.json', timeout=2)" \
        >/dev/null 2>&1; then
        log "CFN responsive (after ${i}s)"
        break
    fi
    sleep 1
    if [[ "$i" == "30" ]]; then
        err "CFN did not come back within 30s.  Check 'docker logs $CFN_CONTAINER'."
        exit 7
    fi
done

if docker exec "$CFN_CONTAINER" grep -q "Site 1 instrumentation" "$SITE1_DST" \
   && docker exec "$CFN_CONTAINER" grep -q "Site 2 instrumentation" "$SITE2_DST"; then
    log "Both Sites verified in container."
else
    err "Site verification failed — patches may not be in the container."
    exit 8
fi

if [[ "$SKIP_BACKEND" == "0" ]]; then
    log "Rebuilding mycelium-backend (capture path for cfn_internal_timing)"
    cd "$COMPOSE_DIR"
    docker compose build mycelium-backend
    docker compose up -d mycelium-backend
    log "mycelium-backend rebuilt."
else
    log "Skipped mycelium-backend rebuild (--skip-backend).  Capture will not include _timing."
fi

log "Done.  Run a smoke test with:  pytest tests/test_mycelium_e2e.py::test_40_distributed_two_agent --analyze-traces"
