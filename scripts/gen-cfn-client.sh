#!/usr/bin/env bash
# Regenerate the CFN (cognition-fabric-node) OpenAPI client.
#
# Pulls /openapi.json from a running ioc-cognition-fabric-node-svc and runs
# openapi-python-client, replacing the committed copy in:
#   - fastapi-backend/ioc_cfn_svc_api_client/
#
# Usage:
#   scripts/gen-cfn-client.sh
#       Assumes CFN is running locally on :9002 (default).
#   CFN_URL=http://other-host:9002 scripts/gen-cfn-client.sh
#       Generates from a different CFN instance.
#
# CFN must be running first. Bring up the stack with:
#   docker compose -f mycelium-cli/src/mycelium/docker/compose.yml --profile cfn up -d

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

CFN_URL="${CFN_URL:-http://localhost:9002}"
SPEC=/tmp/cfn-openapi.json
OUT=/tmp/gen-cfn-client

echo "→ Fetching openapi.json from $CFN_URL"
if ! curl -sfL "$CFN_URL/openapi.json" -o "$SPEC"; then
  echo "✗ Could not reach $CFN_URL/openapi.json" >&2
  echo "  Start CFN first: docker compose -f mycelium-cli/src/mycelium/docker/compose.yml --profile cfn up -d" >&2
  exit 1
fi

echo "→ Generating client at $OUT"
rm -rf "$OUT"
uv run --with openapi-python-client openapi-python-client generate \
  --path "$SPEC" --output-path "$OUT" >/dev/null

echo "→ Copying to fastapi-backend/ioc_cfn_svc_api_client/"
rm -rf "$ROOT/fastapi-backend/ioc_cfn_svc_api_client"
cp -R "$OUT/ioc_cfn_svc_api_client" "$ROOT/fastapi-backend/"

# Format isn't strictly required (the generated client is excluded from ruff
# via extend-exclude) but committed output should still be readable.
echo "→ Running ruff format on generated files"
(cd "$ROOT/fastapi-backend" && uv run ruff format --config 'extend-exclude=[]' ioc_cfn_svc_api_client >/dev/null) || true

echo "✓ Done. Run \`git diff\` to see drift."
