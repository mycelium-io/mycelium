#!/bin/bash
set -euo pipefail
exec > /var/log/e2e-bootstrap.log 2>&1

export DEBIAN_FRONTEND=noninteractive
NODE_ROLE="${node_role}"
NODE_INDEX="${node_index}"

echo "=== Mycelium E2E Bootstrap: role=$NODE_ROLE index=$NODE_INDEX ==="

# --- System packages ---
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl git jq unzip ssh docker.io docker-compose-v2 \
  python3 python3-venv pipx

systemctl enable --now docker
usermod -aG docker ubuntu

# --- Install uv (Python package manager) ---
curl -LsSf https://astral.sh/uv/install.sh | sudo -u ubuntu bash

# --- SSH setup for inter-node communication ---
sudo -u ubuntu mkdir -p /home/ubuntu/.ssh
echo "${ssh_public_key}" >> /home/ubuntu/.ssh/authorized_keys
chmod 600 /home/ubuntu/.ssh/authorized_keys
chown ubuntu:ubuntu /home/ubuntu/.ssh/authorized_keys

# Generate a host key for passwordless inter-node SSH
sudo -u ubuntu ssh-keygen -t ed25519 -f /home/ubuntu/.ssh/id_ed25519 -N ""
cat /home/ubuntu/.ssh/id_ed25519.pub >> /home/ubuntu/.ssh/authorized_keys

# Disable strict host key checking within the VPC
cat >> /home/ubuntu/.ssh/config <<'SSHCFG'
Host 10.100.*
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
  LogLevel ERROR
SSHCFG
chown -R ubuntu:ubuntu /home/ubuntu/.ssh
chmod 600 /home/ubuntu/.ssh/config

# --- Environment variables ---
sudo -u ubuntu mkdir -p /home/ubuntu/.mycelium
cat > /home/ubuntu/.mycelium/.env <<ENVFILE
MYCELIUM_DB_PASSWORD=${mycelium_db_password}
MATRIX_SHARED_SECRET=${matrix_shared_secret}
AWS_ACCESS_KEY_ID=${bedrock_access_key_id}
AWS_SECRET_ACCESS_KEY=${bedrock_secret_access_key}
AWS_DEFAULT_REGION=us-east-1
ENVFILE
chown ubuntu:ubuntu /home/ubuntu/.mycelium/.env
chmod 600 /home/ubuntu/.mycelium/.env

# --- Install Mycelium CLI ---
sudo -u ubuntu /home/ubuntu/.local/bin/uv tool install mycelium-cli

# --- Install OpenClaw ---
sudo -u ubuntu bash -c 'curl -fsSL https://get.openclaw.dev | bash'

# --- Role-specific setup ---
if [ "$NODE_ROLE" = "orchestrator" ]; then
  echo "=== Orchestrator: starting Matrix Synapse + Mycelium backend + CFN ==="

  sudo -u ubuntu mkdir -p /home/ubuntu/.mycelium/docker
  # Docker compose files will be copied by the test workflow after infra is up
  # (they reference the repo and need IP addresses injected)

  # Mark orchestrator ready
  touch /home/ubuntu/.e2e-ready

else
  echo "=== Agent node: waiting for orchestrator config ==="
  # Agent nodes just need OpenClaw gateway running.
  # Full config (openclaw.json, Matrix tokens) injected by orchestrator after boot.
  touch /home/ubuntu/.e2e-ready
fi

echo "=== Bootstrap complete ==="
