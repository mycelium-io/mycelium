#!/usr/bin/env bash
# Refresh the committed openapi.json snapshot from a running backend.
#
# CI diffs this snapshot against the live backend's /openapi.json to detect
# when a route change shipped without a refresh. Regenerating the typed
# clients (mycelium-client/, mycelium-cli/src/mycelium_backend_client/) is a
# separate developer step — see scripts/gen-mycelium-client.sh.
#
# Usage:
#   scripts/snapshot-openapi.sh
#       Fetches from $BACKEND_URL (default http://localhost:8000).

set -euo pipefail

cd "$(dirname "$0")/.."

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"

echo "→ Fetching openapi.json from $BACKEND_URL"
if ! curl -sfL "$BACKEND_URL/openapi.json" -o /tmp/openapi.live.json; then
  echo "✗ Could not reach $BACKEND_URL/openapi.json" >&2
  echo "  Start the backend first: docker compose -f mycelium-cli/src/mycelium/docker/compose.yml up -d mycelium-backend" >&2
  exit 1
fi

python3 -m json.tool /tmp/openapi.live.json > openapi.json
echo "✓ Wrote openapi.json"
