#!/bin/bash
# ec2-setup.sh — Bootstrap a centralized Mycelium backend on an EC2 instance.
#
# Usage:
#   scp ec2-setup.sh ec2-user@<host>:~/
#   ssh ec2-user@<host> bash ec2-setup.sh
#
# Prerequisites: Amazon Linux 2023 or Ubuntu 22.04+ with sudo access.
# The script installs Docker, builds the backend from source, and starts services.

set -euo pipefail

MYCELIUM_REPO="https://github.com/mycelium-io/mycelium.git"
MYCELIUM_DIR="$HOME/mycelium"
DATA_DIR="$HOME/.mycelium"

echo "═══════════════════════════════════════════════════"
echo "  Mycelium Backend — EC2 Setup"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. Install Docker ────────────────────────────────────────────────────────

if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    if command -v apt-get &>/dev/null; then
        # Ubuntu/Debian
        sudo apt-get update -qq
        sudo apt-get install -y -qq docker.io docker-compose-plugin
    elif command -v yum &>/dev/null; then
        # Amazon Linux
        sudo yum install -y docker
        sudo systemctl start docker
        sudo systemctl enable docker
        # Install compose plugin
        DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
        mkdir -p "$DOCKER_CONFIG/cli-plugins"
        curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m)" \
            -o "$DOCKER_CONFIG/cli-plugins/docker-compose"
        chmod +x "$DOCKER_CONFIG/cli-plugins/docker-compose"
    fi
    sudo usermod -aG docker "$USER"
    echo "  ✓ Docker installed"
    echo "  NOTE: You may need to log out and back in for group changes."
    echo "        If docker commands fail, run: newgrp docker"
else
    echo "  ✓ Docker already installed"
fi

# ── 2. Clone repo ────────────────────────────────────────────────────────────

if [ -d "$MYCELIUM_DIR" ]; then
    echo "  Updating existing repo..."
    cd "$MYCELIUM_DIR" && git pull
else
    echo "  Cloning mycelium..."
    git clone "$MYCELIUM_REPO" "$MYCELIUM_DIR"
fi
cd "$MYCELIUM_DIR"
echo "  ✓ Repo ready at $MYCELIUM_DIR"

# ── 3. Create data directory ─────────────────────────────────────────────────

mkdir -p "$DATA_DIR/rooms"
echo "  ✓ Data directory: $DATA_DIR"

# ── 4. Write .env ────────────────────────────────────────────────────────────

ENV_FILE="$DATA_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo ""
    echo "  ── LLM Configuration ──"
    echo "  The backend needs an LLM for synthesis (summarizing room context)."
    echo "  Leave blank to skip (synthesis will be unavailable)."
    echo ""
    read -rp "  LLM model [anthropic/claude-sonnet-4-6]: " LLM_MODEL
    LLM_MODEL="${LLM_MODEL:-anthropic/claude-sonnet-4-6}"
    read -rp "  LLM API key: " LLM_API_KEY
    echo ""

    cat > "$ENV_FILE" << EOF
# Mycelium EC2 backend config
MYCELIUM_DB_PASSWORD=password
MYCELIUM_DATA_DIR=$DATA_DIR

# LLM
LLM_MODEL=$LLM_MODEL
LLM_API_KEY=$LLM_API_KEY
LLM_BASE_URL=

# IoC CFN (disabled)
CFN_MGMT_URL=
CFN_DB=cfn_mgmt
ADMIN_USER_PASSWORD=admin
CFN_DEV_MODE=false
EOF
    echo "  ✓ Wrote $ENV_FILE"
else
    echo "  ~ Using existing $ENV_FILE"
fi

# ── 5. Build and start ───────────────────────────────────────────────────────

COMPOSE_DIR="$MYCELIUM_DIR/mycelium-cli/src/mycelium/docker"
cd "$COMPOSE_DIR"

echo ""
echo "  Building backend image from source..."
docker compose --env-file "$ENV_FILE" build mycelium-backend 2>&1 | tail -3
echo "  ✓ Backend image built"

echo ""
echo "  Starting services..."
docker compose --env-file "$ENV_FILE" up -d mycelium-db mycelium-backend
echo ""

# ── 6. Wait for health ───────────────────────────────────────────────────────

echo "  Waiting for backend to be healthy..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health &>/dev/null; then
        echo "  ✓ Backend healthy"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "  ✗ Backend did not become healthy in 60s"
        echo "    Check: docker logs mycelium-backend"
        exit 1
    fi
    sleep 2
done

# ── 7. Run migrations ────────────────────────────────────────────────────────

echo "  Running database migrations..."
docker exec mycelium-backend python -m alembic upgrade head 2>&1 | tail -3
echo "  ✓ Migrations complete"

# ── 8. Create default workspace ──────────────────────────────────────────────

echo "  Provisioning default workspace..."
curl -sf -X POST http://localhost:8000/workspaces \
    -H "Content-Type: application/json" \
    -d '{"name": "default"}' > /dev/null 2>&1 || true
echo "  ✓ Workspace ready"

# ── 9. Print connection info ─────────────────────────────────────────────────

# Get public IP or hostname
PUBLIC_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || hostname -I | awk '{print $1}')

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Mycelium Backend is running!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  API:        http://${PUBLIC_IP}:8000"
echo "  Health:     http://${PUBLIC_IP}:8000/health"
echo "  API docs:   http://${PUBLIC_IP}:8000/docs"
echo "  Data dir:   $DATA_DIR"
echo ""
echo "  ── Agent Setup (run on each agent's machine) ──"
echo ""
echo "  1. Install the CLI:"
echo "     cd mycelium-cli && uv tool install -e . --with mycelium-backend-client@../mycelium-client --force"
echo ""
echo "  2. Point at this server:"
echo "     mycelium init --force"
echo "     # Enter: http://${PUBLIC_IP}:8000"
echo ""
echo "  3. Create/join a room:"
echo "     mycelium room create my-project"
echo "     mycelium room use my-project"
echo ""
echo "  4. Start sharing context:"
echo "     mycelium memory set \"decisions/first\" \"We're up and running\" --handle my-agent"
echo ""
echo "  ── Git Sync (optional, for multi-machine file access) ──"
echo ""
echo "  On this server:"
echo "     cd $DATA_DIR/rooms/<room> && git init && git add -A && git commit -m 'init'"
echo ""
echo "  On agent machines:"
echo "     mycelium room clone ssh://${PUBLIC_IP}:${DATA_DIR}/rooms/<room>"
echo ""
