#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Boot the SPIRE agent with a join token and register the two MLS-member
# workloads for the #583 spike:
#   spiffe://mycelium.dev/agent/alice   (moderator)
#   spiffe://mycelium.dev/agent/bob     (participant)
#
# Both entries are selected by the host uid running spire_mls_spike.py, so a
# single agent serves both SVIDs; each Python process picks its own via
# SpireConfig.target_spiffe_id.
set -euo pipefail

TD="mycelium.dev"
SERVER="docker compose exec -T spire-server /opt/spire/bin/spire-server"

echo ">> waiting for spire-server ..."
until $SERVER healthcheck >/dev/null 2>&1; do sleep 1; done

echo ">> minting join token + starting agent ..."
TOKEN=$($SERVER token generate -spiffeID "spiffe://${TD}/agent/node" \
  | sed -n 's/^Token: //p')
docker compose exec -d spire-agent /opt/spire/bin/spire-agent run \
  -config /opt/spire/conf/agent/agent.conf -joinToken "$TOKEN"

echo ">> waiting for the agent SVID ..."
sleep 5

# The Python members run on the host. `id -u` here is the host uid; adjust the
# selector if you run the spike inside a container with a different uid.
UID_SEL="unix:uid:$(id -u)"

for leaf in alice bob; do
  echo ">> registering agent/${leaf} (${UID_SEL})"
  $SERVER entry create \
    -parentID "spiffe://${TD}/agent/node" \
    -spiffeID "spiffe://${TD}/agent/${leaf}" \
    -selector "${UID_SEL}" \
    -jwtSVIDTTL 300 || true
done

echo ">> entries:"
$SERVER entry show
echo ">> done. Run spire_mls_spike.py next (see README.md)."
