#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Register the two demo members as SPIRE workloads (#579). Each entry maps a
# workload selector to the SPIFFE ID the `spire` mode expects:
#   spiffe://mycelium.dev/agent/{handle}
#
# The `unix:uid` selector attests any process running as that uid inside the shared
# PID namespace — dev-grade. A real deployment uses a tighter selector (unix:path,
# unix:sha256, k8s:sa, docker:label, ...). Run after the server+agent are up.
set -euo pipefail

TRUST_DOMAIN="${TRUST_DOMAIN:-mycelium.dev}"
# The parent SPIFFE ID is the attested agent node; the server prints it as the
# agent's SVID. For the join-token agent it is spiffe://<td>/spire/agent/join_token/<token>.
PARENT_ID="${PARENT_ID:?set PARENT_ID to the agent node SPIFFE ID (see run.sh)}"
# uid the member processes run as inside the shared PID namespace.
WORKLOAD_UID="${WORKLOAD_UID:-$(id -u)}"

register() {
  local handle="$1"
  docker compose exec -T spire-server \
    /opt/spire/bin/spire-server entry create \
      -parentID "$PARENT_ID" \
      -spiffeID "spiffe://${TRUST_DOMAIN}/agent/${handle}" \
      -selector "unix:uid:${WORKLOAD_UID}" \
      -jwtSVIDTTL 300
}

for handle in "${@:-alice bob}"; do
  echo "== registering spiffe://${TRUST_DOMAIN}/agent/${handle} =="
  register "$handle"
done
