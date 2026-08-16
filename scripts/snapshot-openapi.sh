#!/usr/bin/env bash
# Refresh the committed openapi.json snapshot from the backend app.
#
# The snapshot is the single source of truth for the typed clients: they are
# build artifacts generated from this file (scripts/gen-mycelium-client.sh),
# not checked-in source. CI regenerates the snapshot the same way and fails if
# it differs from the committed one, so a route change that skips this script
# is a red gate rather than a client that silently 404s.
#
# The spec is read straight out of the FastAPI app object — no server, no
# database, no SLIM node. Only the backend's dependencies are needed.
#
# Usage:
#   scripts/snapshot-openapi.sh          Rewrite openapi.json in place.
#   scripts/snapshot-openapi.sh --check  Exit non-zero if it is out of date.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

CHECK=false
if [ "${1:-}" = "--check" ]; then
  CHECK=true
fi

OUT=$(mktemp)
trap 'rm -f "$OUT"' EXIT

echo "→ Dumping the OpenAPI spec from app.main:app"
(cd "$ROOT/fastapi-backend" && uv run --frozen python -c '
import json
import sys

from app.main import app

json.dump(app.openapi(), sys.stdout, indent=4, sort_keys=True)
sys.stdout.write("\n")
') > "$OUT"

if [ "$CHECK" = true ]; then
  if diff -u openapi.json "$OUT" > /tmp/openapi.drift.diff; then
    echo "✓ openapi.json matches the backend app"
  else
    head -40 /tmp/openapi.drift.diff
    echo ""
    echo "✗ openapi.json is stale — the backend's API changed without a snapshot." >&2
    echo "  Refresh it with: scripts/snapshot-openapi.sh" >&2
    exit 1
  fi
else
  cp "$OUT" openapi.json
  echo "✓ Wrote openapi.json"
  echo "  Regenerate the typed clients with: scripts/gen-mycelium-client.sh"
fi
