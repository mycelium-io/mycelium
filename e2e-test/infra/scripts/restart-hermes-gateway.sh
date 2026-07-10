#!/usr/bin/env bash
# Restart the supervisord-managed hermes gateway so it reloads config.yaml.
#
# ``mycelium agent create`` patches ~/.hermes/config.yaml but cannot restart
# a foreground gateway in containers (no systemd). Supervisord autorestarts the
# process when we signal the old one.

set -euo pipefail

if ! pgrep -f 'hermes gateway run' >/dev/null 2>&1; then
    echo "[restart-hermes-gateway] no running gateway — skipping"
    exit 0
fi

pkill -f 'hermes gateway run' || true
sleep 2
if pgrep -f 'hermes gateway run' >/dev/null 2>&1; then
    echo "[restart-hermes-gateway] gateway still running after pkill"
else
    echo "[restart-hermes-gateway] signalled gateway — waiting for supervisord autorestart"
fi
