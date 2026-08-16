#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# One-command reproduction of the #583 spike. Stands up SPIRE server + agent + a
# stock SLIM 2.1.0 node, registers two workloads, and runs the two-member MLS
# exchange inside a Linux runner container. Exits non-zero unless the runner
# prints PASS. This is the exact sequence that produced the PASS in README.md.
set -euo pipefail
cd "$(dirname "$0")"

TD="mycelium.dev"
srv() { docker compose exec -T spire-server /opt/spire/bin/spire-server "$@"; }

echo ">> [1/6] SPIRE server + SLIM node"
docker compose up -d spire-server slim >/dev/null
until srv healthcheck >/dev/null 2>&1; do sleep 1; done

echo ">> [2/6] mint one-time join token + start agent"
docker compose rm -sf spire-agent >/dev/null 2>&1 || true
TOKEN=$(srv token generate -spiffeID "spiffe://${TD}/agent/node" | sed -n 's/^Token: //p')
JOIN_TOKEN="$TOKEN" docker compose up -d spire-agent >/dev/null

echo ">> [3/6] register alice + bob workloads (unix:uid:0 -> runner container)"
for leaf in alice bob; do
  srv entry create -parentID "spiffe://${TD}/agent/node" \
    -spiffeID "spiffe://${TD}/agent/${leaf}" \
    -selector "unix:uid:0" -jwtSVIDTTL 300 >/dev/null 2>&1 || true
done

echo ">> [4/6] wait for the agent to mint the SVIDs"
until docker compose logs spire-agent 2>&1 | grep -q "agent/bob"; do sleep 1; done

echo ">> [5/6] start runner in the agent's PID namespace + install slim-bindings==2.1.0"
docker compose rm -sf runner >/dev/null 2>&1 || true
docker compose up -d --no-deps runner >/dev/null
docker compose exec -T runner pip install --quiet --root-user-action=ignore \
  'slim-bindings==2.1.0' >/dev/null

echo ">> [6/6] run the two-member SPIRE-MLS exchange"
docker compose exec -T runner python /spike/spire_mls_spike.py
