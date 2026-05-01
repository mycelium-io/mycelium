#!/usr/bin/env bash
# Regenerate the Mycelium backend OpenAPI client.
#
# Pulls /openapi.json from a running backend and runs openapi-python-client,
# replacing the committed copies in:
#   - mycelium-client/                     (standalone package, has pyproject.toml)
#   - mycelium-cli/src/mycelium_backend_client/  (vendored copy the CLI imports)
#
# Usage:
#   scripts/gen-mycelium-client.sh
#       Boots the backend via docker compose if BACKEND_URL is unset.
#   BACKEND_URL=http://localhost:8000 scripts/gen-mycelium-client.sh
#       Uses an already-running backend.
#
# Exit codes:
#   0 — regenerated; check `git diff` to see drift.
#   non-zero — generation failed; committed clients unchanged.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
SPEC=/tmp/mycelium-openapi.json
OUT=/tmp/gen-mycelium-client

echo "→ Fetching openapi.json from $BACKEND_URL"
if ! curl -sfL "$BACKEND_URL/openapi.json" -o "$SPEC"; then
  echo "✗ Could not reach $BACKEND_URL/openapi.json" >&2
  echo "  Start the backend first: docker compose -f mycelium-cli/src/mycelium/docker/compose.yml up -d mycelium-backend" >&2
  exit 1
fi

echo "→ Generating client at $OUT"
rm -rf "$OUT"
uv run --with 'openapi-python-client==0.28.3' openapi-python-client generate \
  --path "$SPEC" --output-path "$OUT" >/dev/null

echo "→ Copying to mycelium-client/"
rm -rf "$ROOT/mycelium-client/mycelium_backend_client"
cp -R "$OUT/mycelium_backend_client" "$ROOT/mycelium-client/"

echo "→ Copying to mycelium-cli/src/mycelium_backend_client/"
rm -rf "$ROOT/mycelium-cli/src/mycelium_backend_client"
cp -R "$OUT/mycelium_backend_client" "$ROOT/mycelium-cli/src/"

# Format with a pinned ruff so committed output is byte-identical between
# local devs and CI regardless of project lockfile drift.
echo "→ Running ruff format on generated files"
RUFF_PIN='ruff==0.15.10'
(cd "$ROOT/mycelium-cli" && uv run --with "$RUFF_PIN" ruff format src/mycelium_backend_client >/dev/null)
(cd "$ROOT/mycelium-cli" && uv run --with "$RUFF_PIN" ruff format ../mycelium-client/mycelium_backend_client >/dev/null)

echo "✓ Done. Run \`git diff\` to see drift."
