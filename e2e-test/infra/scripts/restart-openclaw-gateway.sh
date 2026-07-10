#!/usr/bin/env bash
# Restart the supervisord-managed OpenClaw gateway so plugin patches take effect.

set -euo pipefail

if ! pgrep -f 'openclaw gateway' >/dev/null 2>&1; then
    echo "[restart-openclaw-gateway] no running gateway — skipping"
    exit 0
fi

pkill -f 'openclaw gateway' || true
sleep 2
if pgrep -f 'openclaw gateway' >/dev/null 2>&1; then
    echo "[restart-openclaw-gateway] gateway still running after pkill"
else
    echo "[restart-openclaw-gateway] signalled gateway — waiting for supervisord autorestart"
fi
