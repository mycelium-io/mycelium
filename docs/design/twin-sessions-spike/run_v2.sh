#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Spike #662 v2: faithful two-process twin restart matrix.
#
# Stands up a stock SLIM 2.1.0 node, mints one ES256 keypair per handle
# (mod, mod2, alice, bob) + a roster JWKS, then runs the orchestrator, which
# spawns real subprocesses it can SIGKILL to test restarts across a true process
# boundary (drops the conn; the node forgets the subscription).
#
# Requires: docker, openssl, the fastapi-backend uv env (slim-bindings==2.1.0 +
# cryptography). Run from this directory. Tear-down is automatic.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/../../../fastapi-backend" && pwd)"
NODE_NAME="slim-twin-sessions-spike-v2"
NODE_PORT="${NODE_PORT:-46360}"
KEYDIR="${KEYDIR:-/tmp/twin-sessions-spike}"
# Distinct handles per test so the shared node's per-Name multicast queue can't
# leak messages between scenarios (see spike_v2.py isolation note).
HANDLES="${HANDLES:-d1mod d1alice d2mod d2alice d2bob d3mod d3alice amod aalice bmod bmod2 balice}"
export SLIM_ENDPOINT="http://127.0.0.1:${NODE_PORT}"
export KEYDIR

cleanup() { docker rm -f "$NODE_NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 1/3  stock SLIM 2.1.0 node on :${NODE_PORT} =="
mkdir -p "${KEYDIR:?}"
cat > "$KEYDIR/slim-node-v2.yaml" <<EOF
tracing: { log_level: error }
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
  -v "$KEYDIR/slim-node-v2.yaml:/config.yaml" \
  ghcr.io/agntcy/slim:2.1.0 /slim --config /config.yaml >/dev/null
sleep 3

echo "== 2/3  self-mint each handle's ES256 keypair (PKCS#8) + roster JWKS =="
for name in $HANDLES; do
  openssl ecparam -name prime256v1 -genkey -noout -out "$KEYDIR/$name.sec1.key" 2>/dev/null
  openssl pkcs8 -topk8 -nocrypt -in "$KEYDIR/$name.sec1.key" -out "$KEYDIR/$name.pk8.pem" 2>/dev/null
  openssl ec -in "$KEYDIR/$name.sec1.key" -pubout -out "$KEYDIR/$name.pub.pem" 2>/dev/null
done
# shellcheck disable=SC2086
( cd "$BACKEND" && uv run python "$HERE/build_roster_jwks.py" "$KEYDIR" $HANDLES )

echo "== 3/3  restart matrix (real subprocesses, SIGKILL) =="
( cd "$BACKEND" && uv run python "$HERE/spike_v2.py" )
