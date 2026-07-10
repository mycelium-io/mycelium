#!/usr/bin/env bash
# Convert a native Mycelium lab spoke (host openclaw / hermes / mycelium-daemon)
# into an all-in-one docker-compose E2E stack on the same machine.
#
# Typical use: repurpose oclw3 (or any single-host lab box) from the native
# three-gateway layout to the full compose topology (db, CFN, backend, matrix,
# collector, hub, two spokes) so pyATS can run against testbeds/compose.yaml
# without a separate CI runner.
#
# Usage:
#   ./scripts/native_to_compose_lab.sh                  # full conversion
#   ./scripts/native_to_compose_lab.sh --dry-run        # print planned steps
#   ./scripts/native_to_compose_lab.sh --skip-native-stop   # stack only
#   MYCELIUM_SPOKE_IMAGE=mycelium-spoke:lab ./scripts/native_to_compose_lab.sh
#
# Environment (optional):
#   E2E_REPO_DIR          checkout path (default: ~/mycelium-e2e-test)
#   MYCELIUM_SPOKE_IMAGE  spoke/hub-side image with baked CLI (see --build-spoke-image)
#   SPOKE_ADAPTERS        default: openclaw,hermes
#   LLM_MODEL/API_KEY/BASE_URL — read from ~/.mycelium/.env when present
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$REPO_ROOT/infra/compose.e2e.yaml}"
E2E_REPO_DIR="${E2E_REPO_DIR:-$HOME/mycelium-e2e-test}"
HUB_ADAPTERS="${HUB_ADAPTERS:-openclaw,hermes}"
SPOKE_ADAPTERS="${SPOKE_ADAPTERS:-openclaw,cursor,hermes}"
HOST_CURSOR_AUTH="${HOST_CURSOR_AUTH:-${HOME}/.config/cursor/auth.json}"
HUB_CONTAINER="${HUB_CONTAINER:-e2e-openclaw-hub}"
SPOKE1_CONTAINER="${SPOKE1_CONTAINER:-e2e-openclaw-spoke1}"
SPOKE2_CONTAINER="${SPOKE2_CONTAINER:-e2e-openclaw-spoke2}"

DRY_RUN=false
SKIP_NATIVE_STOP=false
SKIP_BOOTSTRAP=false
SKIP_HUB_ADAPTER="${SKIP_HUB_ADAPTER:-true}"
BUILD_SPOKE_IMAGE=false
MYCELIUM_WHEEL=""
MYCELIUM_REPO=""
BACKUP_DIR=""

log() { printf '[native→compose] %s\n' "$*"; }
run() {
    if $DRY_RUN; then
        printf '[dry-run]'
        printf ' %q' "$@"
        printf '\n'
    else
        log "→ $*"
        "$@"
    fi
}

run_shell() {
    if $DRY_RUN; then
        printf '[dry-run] %s\n' "$1"
    else
        log "→ $1"
        bash -c "$1"
    fi
}

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    cat <<EOF

Options:
  --dry-run              Print commands without executing
  --skip-native-stop     Assume native gateways are already stopped
  --skip-bootstrap       Skip matrix/mycelium bootstrap (volume already seeded)
  --skip-hub-adapter     Do not run mycelium adapter add on the hub
  --build-spoke-image    Build MYCELIUM_SPOKE_IMAGE locally (needs wheel or repo)
  --mycelium-wheel PATH  Pre-built mycelium_cli wheel for spoke image
  --mycelium-repo PATH   Mycelium source tree; build wheel if --build-spoke-image
  --backup-dir PATH      Tar ~/.openclaw ~/.hermes ~/.mycelium before stopping native
  -h, --help             Show this help
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --skip-native-stop) SKIP_NATIVE_STOP=true; shift ;;
        --skip-bootstrap) SKIP_BOOTSTRAP=true; shift ;;
        --skip-hub-adapter) SKIP_HUB_ADAPTER=true; shift ;;
        --build-spoke-image) BUILD_SPOKE_IMAGE=true; shift ;;
        --mycelium-wheel) MYCELIUM_WHEEL="$2"; shift 2 ;;
        --mycelium-repo) MYCELIUM_REPO="$2"; shift 2 ;;
        --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
    esac
done

# ── Helpers ─────────────────────────────────────────────────────────────

detect_openclaw() {
    if command -v openclaw &>/dev/null; then
        command -v openclaw
        return 0
    fi
    local nvm_glob
    for nvm_glob in "$HOME"/.nvm/versions/node/*/bin/openclaw; do
        [[ -x "$nvm_glob" ]] && { echo "$nvm_glob"; return 0; }
    done
    return 1
}

stop_user_unit() {
    local unit="$1"
    if systemctl --user list-unit-files "$unit" &>/dev/null; then
        run_shell "systemctl --user stop $unit 2>/dev/null || true"
        run_shell "systemctl --user disable $unit 2>/dev/null || true"
    fi
}

wait_healthy() {
    local container="$1" timeout="${2:-120}" label="${3:-$1}"
    if $DRY_RUN; then
        log "would wait for $label healthy (${timeout}s max)"
        return 0
    fi
    for ((i = 1; i <= timeout / 2; i++)); do
        local status
        status="$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null || echo missing)"
        if [[ "$status" == "healthy" ]]; then
            log "$label healthy (~$((i * 2))s)"
            return 0
        fi
        sleep 2
    done
    log "WARNING: $label not healthy after ${timeout}s (status=$status)"
    docker logs "$container" --tail 30 2>/dev/null || true
    return 1
}

load_llm_env() {
    if [[ -f "$HOME/.mycelium/.env" ]]; then
        log "Loading LLM credentials from ~/.mycelium/.env"
        set -a
        # shellcheck disable=SC1091
        source "$HOME/.mycelium/.env"
        set +a
    fi
    if [[ -z "${LLM_API_KEY:-}" || -z "${LLM_BASE_URL:-}" ]]; then
        log "WARNING: LLM_API_KEY / LLM_BASE_URL not set — CFN/coordination tests may skip"
    fi
    export LLM_MODEL LLM_API_KEY LLM_BASE_URL
}

ensure_host_mycelium() {
    if command -v mycelium &>/dev/null; then
        log "Host mycelium: $(mycelium --version 2>/dev/null || echo present)"
        return 0
    fi
    log "Installing mycelium CLI on host..."
    run_shell "curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash"
    export PATH="$HOME/.local/bin:$PATH"
}

ensure_e2e_repo() {
    if [[ ! -d "$E2E_REPO_DIR/.git" ]]; then
        run git clone https://github.com/mycelium-io/mycelium-e2e-test.git "$E2E_REPO_DIR"
    else
        run git -C "$E2E_REPO_DIR" fetch --quiet origin
        run_shell "git -C '$E2E_REPO_DIR' pull --ff-only || true"
    fi
    COMPOSE_FILE="$E2E_REPO_DIR/infra/compose.e2e.yaml"
}

build_spoke_image_if_requested() {
    $BUILD_SPOKE_IMAGE || return 0

    local wheel="$MYCELIUM_WHEEL" repo="$MYCELIUM_REPO" wheel_dir
    wheel_dir="$(mktemp -d)"
    trap 'rm -rf "$wheel_dir"' RETURN

    if [[ -n "$wheel" ]]; then
        cp "$wheel" "$wheel_dir/"
    elif [[ -n "$repo" ]]; then
        log "Building mycelium CLI wheel from $repo"
        if $DRY_RUN; then
            log "[dry-run] would build wheel from $repo"
            export MYCELIUM_SPOKE_IMAGE="${MYCELIUM_SPOKE_IMAGE:-mycelium-spoke:lab}"
            return 0
        fi
        (cd "$repo/mycelium-cli" && uv run --with build python -m build --wheel --outdir "$wheel_dir")
    else
        echo "ERROR: --build-spoke-image requires --mycelium-wheel or --mycelium-repo" >&2
        exit 2
    fi

    local whl_file
    whl_file="$(ls -t "$wheel_dir"/mycelium_cli-*.whl 2>/dev/null | head -1)"
    [[ -n "$whl_file" ]] || { echo "ERROR: no mycelium_cli wheel found" >&2; exit 1; }

    local image="${MYCELIUM_SPOKE_IMAGE:-mycelium-spoke:lab}"
    export MYCELIUM_SPOKE_IMAGE="$image"
    local whl_basename
    whl_basename="$(basename "$whl_file")"
    cp "$whl_file" "$E2E_REPO_DIR/infra/$whl_basename"

    log "Building spoke image $image (uv + Python 3.12 + mycelium CLI)"
    if $DRY_RUN; then
        log "[dry-run] docker build -t $image ..."
        return 0
    fi

    docker build -f - -t "$image" "$E2E_REPO_DIR" <<DOCKERFILE
FROM ghcr.io/mycelium-io/mycelium-spoke:latest
USER root
COPY infra/$whl_basename /tmp/$whl_basename
ENV UV_PYTHON_INSTALL_DIR=/usr/local/share/uv/python
RUN curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local sh \\
    && /usr/local/uv python install 3.12 \\
    && UV_TOOL_DIR=/usr/local/share/uv/tools /usr/local/uv tool install --python 3.12 \\
         --force --from /tmp/$whl_basename mycelium-cli \\
    && chmod -R a+rX /usr/local/share/uv \\
    && ln -sf /usr/local/share/uv/tools/mycelium-cli/bin/mycelium /usr/local/bin/mycelium \\
    && rm -f /tmp/$whl_basename \\
    && su - spoke -c 'mycelium --version'
COPY infra/scripts/spoke-entrypoint.sh /openclaw/entrypoint.sh
RUN chmod +x /openclaw/entrypoint.sh
ENV PATH="/usr/local/bin:/usr/local/share/uv/tools/mycelium-cli/bin:\${PATH}"
USER spoke
DOCKERFILE
    rm -f "$E2E_REPO_DIR/infra/$whl_basename"
}

compose() {
    run docker compose -f "$COMPOSE_FILE" "$@"
}

# ── Phase 1: stop native gateways ─────────────────────────────────────

stop_native_gateways() {
    $SKIP_NATIVE_STOP && { log "Skipping native gateway stop"; return 0; }

    if [[ -n "$BACKUP_DIR" ]]; then
        run mkdir -p "$BACKUP_DIR"
        local ts
        ts="$(date -u +%Y%m%dT%H%M%SZ)"
        for d in .openclaw .hermes .mycelium; do
            if [[ -d "$HOME/$d" ]]; then
                run tar -czf "$BACKUP_DIR/${d}.${ts}.tgz" -C "$HOME" "$d"
            fi
        done
    fi

    local openclaw_bin
    if openclaw_bin="$(detect_openclaw)"; then
        log "Stopping native OpenClaw ($openclaw_bin)"
        run_shell "'$openclaw_bin' gateway stop 2>/dev/null || true"
    fi
    stop_user_unit openclaw-gateway.service

    if command -v hermes &>/dev/null; then
        log "Stopping native Hermes"
        run_shell "hermes gateway stop 2>/dev/null || true"
    fi
    stop_user_unit hermes-gateway.service
    stop_user_unit mycelium-daemon.service
    stop_user_unit mycelium-cc-daemon.service

    if docker ps -a --format '{{.Names}}' | grep -qx openclaw-matrix; then
        run_shell "docker stop openclaw-matrix 2>/dev/null || true"
    fi

    log "Checking well-known ports are free (8000 backend, 8008 matrix, 18789 hub)..."
    if ! $DRY_RUN; then
        for port in 8000 8008 18789; do
            if ss -tln | grep -q ":${port} "; then
                log "WARNING: port $port still in use — compose may fail to bind"
                ss -tlnp | grep ":${port} " || true
            fi
        done
    fi
}

# ── Phase 2: compose stack (mirrors .github/workflows/e2e.yml) ────────

bring_up_compose() {
    cd "$E2E_REPO_DIR"
    load_llm_env
    export HUB_ADAPTERS SPOKE_ADAPTERS
    if [[ ! -f "$HOST_CURSOR_AUTH" ]]; then
        log "HOST_CURSOR_AUTH missing ($HOST_CURSOR_AUTH) — using /dev/null"
        HOST_CURSOR_AUTH=/dev/null
    fi
    export HOST_CURSOR_AUTH
    [[ -n "${MYCELIUM_SPOKE_IMAGE:-}" ]] && export MYCELIUM_SPOKE_IMAGE

    compose up -d mycelium-db matrix-synapse
    compose up -d ioc-cfn-mgmt-plane-svc ioc-cfn-svc
    compose up -d mycelium-backend

    for svc in e2e-mycelium-db e2e-matrix-synapse e2e-cfn-mgmt e2e-cfn-node e2e-mycelium-backend; do
        wait_healthy "$svc" 180 "$svc" || true
    done

    if ! $SKIP_BOOTSTRAP; then
        compose --profile bootstrap run --rm matrix-bootstrap
        compose --profile bootstrap run --rm mycelium-bootstrap

        local project volume
        project="$(docker compose -f "$COMPOSE_FILE" config --format json | python3 -c "import sys,json; print(json.load(sys.stdin).get('name','infra'))")"
        volume="${project}_e2e-shared"
        log "Reading workspace/MAS IDs from volume $volume"
        if ! $DRY_RUN; then
            eval "$(docker run --rm -v "${volume}:/shared:ro" python:3.12-slim python3 -c "
import json, pathlib
p = pathlib.Path('/shared/mycelium-config.json')
if p.exists():
    cfg = json.loads(p.read_text())
    for key in ('workspace_id', 'mas_id'):
        v = cfg.get(key, '')
        if v:
            print(f'export {key.upper()}={v}')
" 2>/dev/null || true)"
            if [[ -n "${WORKSPACE_ID:-}" || -n "${MAS_ID:-}" ]]; then
                compose stop mycelium-backend
                export WORKSPACE_ID MAS_ID
                compose up -d mycelium-backend
                wait_healthy e2e-mycelium-backend 60 backend
            fi
        fi
    fi

    compose up -d --no-recreate mycelium-collector
    wait_healthy e2e-mycelium-collector 60 collector || true

    compose up -d --no-recreate openclaw-hub
    wait_healthy "$HUB_CONTAINER" 180 hub || true

    compose up -d --no-recreate openclaw-spoke1 openclaw-spoke2
    for svc in "$SPOKE1_CONTAINER" "$SPOKE2_CONTAINER"; do
        wait_healthy "$svc" 180 "$svc" || true
    done
}

register_hub_openclaw_adapter() {
    $SKIP_HUB_ADAPTER && { log "Skipping hub openclaw adapter registration"; return 0; }
    ensure_host_mycelium
    export PATH="$HOME/.local/bin:$PATH"

    log "Registering openclaw adapter on $HUB_CONTAINER (host → docker cp path)"
    run mycelium adapter add openclaw --openclaw-container "$HUB_CONTAINER" --reinstall --yes
    run bash -c "mycelium adapter add openclaw --openclaw-container '$HUB_CONTAINER' --step=otel --yes 2>/dev/null || true"
    run docker restart "$HUB_CONTAINER"
    wait_healthy "$HUB_CONTAINER" 120 hub || true
}

verify_stack() {
    log "=== Verification ==="
    if $DRY_RUN; then return 0; fi

    curl -sf "http://localhost:${E2E_BACKEND_PORT:-8000}/health" | head -c 120 || log "backend /health failed"
    echo

    for role_container in "hub:$HUB_CONTAINER" "spoke1:$SPOKE1_CONTAINER" "spoke2:$SPOKE2_CONTAINER"; do
        local role="${role_container%%:*}" container="${role_container#*:}"
        echo "--- $role ($container) ---"
        docker inspect --format='{{.State.Status}} health={{.State.Health.Status}}' "$container" 2>/dev/null || echo missing
        docker exec "$container" sh -c '
            for d in /home/spoke/.openclaw /home/node/.openclaw; do
                if [ -f "$d/extensions/mycelium/dist/index.js" ]; then
                    echo "plugin: $d/extensions/mycelium"
                    python3 -c "import json,sys; c=json.load(open(sys.argv[1])); print(\"mycelium-room\", \"mycelium-room\" in c.get(\"channels\",{}))" "$d/openclaw.json" 2>/dev/null
                fi
            done
        ' 2>/dev/null || true
    done

    log "Run pyATS: cd '$E2E_REPO_DIR' && MYCELIUM_E2E_RUNTIME=compose uv run pyats run job jobs/pr_job.py --testbed-file testbeds/compose.yaml"
}

# ── Main ──────────────────────────────────────────────────────────────

main() {
    command -v docker &>/dev/null || { echo "ERROR: docker required" >&2; exit 1; }
    docker compose version &>/dev/null || { echo "ERROR: docker compose v2 required" >&2; exit 1; }

    ensure_e2e_repo
    build_spoke_image_if_requested
    stop_native_gateways
    bring_up_compose
    register_hub_openclaw_adapter
    verify_stack
    log "Done."
}

main "$@"
