#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# One-command reproduction of the server-side per-actor "twin" SLIM/MLS spike (#662).
#
# Stands up a stock SLIM 2.1.0 node, self-mints one ES256 keypair per twin (the
# moderator + N per-actor twins) plus a room roster JWKS, then runs the whole twin
# fleet in ONE host process: N persistence-backed, SignerJwt-identified MLS members
# in one GROUP, plus a restore_sessions resume of one twin.
#
# Requires: docker, openssl, and the fastapi-backend uv env (slim-bindings==2.1.0 +
# cryptography). Run from this directory. Tear-down is automatic.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/../../../fastapi-backend" && pwd)"
NODE_NAME="slim-twin-sessions-spike"
NODE_PORT="${NODE_PORT:-46359}"   # not :46357 (dev node) / :46358 (signerjwt spike)
KEYDIR="${KEYDIR:-/tmp/twin-sessions-spike}"
TWINS="${TWINS:-backend alice bob carol}"
export SLIM_ENDPOINT="http://127.0.0.1:${NODE_PORT}"
export KEYDIR TWINS

cleanup() { docker rm -f "$NODE_NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 1/3  stock SLIM 2.1.0 node on :${NODE_PORT} =="
mkdir -p "${KEYDIR:?}"
cat > "$KEYDIR/slim-node.yaml" <<EOF
tracing: { log_level: info }
runtime: { n_cores: 0, thread_name: "slim-data-plane", drain_timeout: 10s }
services:
  slim/0:
    dataplane:
      servers:
        - endpoint: "0.0.0.0:${NODE_PORT}"
          tls: { insecure: true }
      clients: []
EOF
cleanup
docker run -d --name "$NODE_NAME" -p "${NODE_PORT}:${NODE_PORT}" \
  -v "$KEYDIR/slim-node.yaml:/config.yaml" \
  ghcr.io/agntcy/slim:2.1.0 /slim --config /config.yaml >/dev/null
sleep 3

echo "== 2/3  self-mint each twin's ES256 keypair (PKCS#8) + roster JWKS =="
for name in $TWINS; do
  openssl ecparam -name prime256v1 -genkey -noout -out "$KEYDIR/$name.sec1.key" 2>/dev/null
  openssl pkcs8 -topk8 -nocrypt -in "$KEYDIR/$name.sec1.key" -out "$KEYDIR/$name.pk8.pem" 2>/dev/null
  openssl ec -in "$KEYDIR/$name.sec1.key" -pubout -out "$KEYDIR/$name.pub.pem" 2>/dev/null
done
# shellcheck disable=SC2086 -- word-splitting $TWINS into roster args is intended
( cd "$BACKEND" && uv run python "$HERE/build_roster_jwks.py" "$KEYDIR" $TWINS )

echo "== 3/3  N per-actor twins share one MLS GROUP + one resumes from persistence =="
( cd "$BACKEND" && uv run python "$HERE/twin_sessions_spike.py" )
