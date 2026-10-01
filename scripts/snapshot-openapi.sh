#!/usr/bin/env bash
# Refresh the committed openapi.json snapshot from the backend's source.
#
# CI checks this snapshot against `app.openapi()` run in the backend's locked
# environment (uv.lock), so that is what this writes too, and no backend has
# to be running. It used to fetch /openapi.json from a running backend, but
# the Docker image can carry a newer FastAPI than the lock (one that adds
# `ctx`/`input` to ValidationError), so a snapshot taken there failed CI.
# Regenerating the typed client is a separate step: scripts/gen-mycelium-client.sh.
#
# Usage:
#   scripts/snapshot-openapi.sh

set -euo pipefail

cd "$(dirname "$0")/.."

echo "→ Building the spec from fastapi-backend/ (locked environment)"
spec="$(mktemp)"
trap 'rm -f "$spec"' EXIT
(cd fastapi-backend && uv run --frozen python -c \
  'import json; from app.main import app; print(json.dumps(app.openapi()))') > "$spec"

# indent=2 matches the committed file, so a refresh shows only the real change.
python3 -m json.tool --indent 2 "$spec" > openapi.json
echo "✓ Wrote openapi.json"
