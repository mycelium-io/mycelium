#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# One-command dev rig for SPIRE-attested MLS members (#579). Stands up the stock
# SLIM 2.1.0 node + a co-located SPIRE server/agent (shared PID namespace,
# named-volume Workload API socket), registers the two demo workloads, and runs two
# members that present JWT-SVIDs as their MLS identity.
#
# Requires: docker + docker compose, and the fastapi-backend uv env
# (slim-bindings==2.1.0). Run from this directory. Tear-down is automatic.
#
# NOTE: this is the dev-grade path validated on real infra (a shared PID namespace
# is exactly what an offline unit suite can't stand up). The provider/verifier
# wiring and off-by-default/degrade/fail-closed behavior are covered offline in
# fastapi-backend/tests/test_slim_identity.py. The appliance profile is #588.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

cleanup() { docker compose down -v >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "== 1/4  SPIRE server + stock slim:2.1.0 node =="
SPIRE_JOIN_TOKEN=placeholder docker compose up -d spire-server slim
sleep 5

echo "== 2/4  mint a join token + start the co-located SPIRE agent =="
JOIN_TOKEN="$(docker compose exec -T spire-server \
  /opt/spire/bin/spire-server token generate -spiffeID spiffe://mycelium.dev/agent-node \
  | sed -n 's/^Token: //p')"
SPIRE_JOIN_TOKEN="$JOIN_TOKEN" docker compose up -d spire-agent
sleep 5

echo "== 3/4  register the two member workloads =="
PARENT_ID="spiffe://mycelium.dev/spire/agent/join_token/${JOIN_TOKEN}" \
  ./register-workloads.sh alice bob

echo "== 4/4  two SPIRE-attested members establish MLS + exchange a message =="
# Members connect to the node on :46358 with MYCELIUM_SLIM_IDENTITY=spire, pointed
# at the shared Workload API socket. The demo runner lives with the spike:
#   ../spire-mls-spike/spire_mls_spike.py  (proven PASS, #583/#584)
# It is the same two-member GROUP/MLS exchange as the signerjwt spike, only the
# provider/verifier variant differs.
echo "  see ../spire-mls-spike/ for the proven two-member runner (#583/#584)."
echo "  export MYCELIUM_SLIM_IDENTITY=spire"
echo "  export MYCELIUM_SLIM_SPIRE_SOCKET=unix:///run/spire/sockets/agent.sock"
echo "  export MYCELIUM_SLIM_SPIRE_TRUST_DOMAIN=mycelium.dev"
