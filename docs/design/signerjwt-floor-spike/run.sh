#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# One-command reproduction of the SignerJwt floor -> SLIM MLS spike (#587).
#
# Unlike the #583 SPIRE spike this needs NO SPIRE, NO shared PID namespace, and NO
# in-container runner: the whole point of the floor is that a resident agent on its
# own machine self-mints its credential. So this stands up a stock SLIM 2.1.0 node
# and runs the two members straight on the host.
#
# Requires: docker, openssl, and the fastapi-backend uv env (slim-bindings==2.1.0 +
# cryptography). Run from this directory. Tear-down is automatic.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$(cd "$HERE/../../../fastapi-backend" && pwd)"
NODE_NAME="slim-signerjwt-spike"
NODE_PORT="${NODE_PORT:-46358}"   # not :46357 -- the dev node owns that
KEYDIR="${KEYDIR:-/tmp/signerjwt-floor-spike}"
export SLIM_ENDPOINT="http://127.0.0.1:${NODE_PORT}"
export KEYDIR

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

echo "== 2/3  self-mint each member's ES256 keypair (PKCS#8) + roster JWKS =="
for name in alice bob; do
  # ecparam emits SEC1 -> InvalidKeyFormat; convert to PKCS#8 for the signer.
  openssl ecparam -name prime256v1 -genkey -noout -out "$KEYDIR/$name.sec1.key" 2>/dev/null
  openssl pkcs8 -topk8 -nocrypt -in "$KEYDIR/$name.sec1.key" -out "$KEYDIR/$name.pk8.pem" 2>/dev/null
  openssl ec -in "$KEYDIR/$name.sec1.key" -pubout -out "$KEYDIR/$name.pub.pem" 2>/dev/null
done
( cd "$BACKEND" && uv run python "$HERE/build_roster_jwks.py" "$KEYDIR" alice bob )

echo "== 3/3  two SignerJwt members establish MLS + exchange a message =="
( cd "$BACKEND" && uv run python "$HERE/signerjwt_floor_spike.py" )
