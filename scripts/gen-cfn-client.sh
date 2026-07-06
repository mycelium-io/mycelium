#!/usr/bin/env bash
# Regenerate the typed CFN (ioc-cfn-svc) client from the Go service's swagger.
#
# The Go CFN serves Swagger 2.0 at /docs/swagger.json (swaggo). openapi-python-client
# only consumes OpenAPI 3.x, so we convert first with swagger2openapi (npx).
#
# Source of truth is the committed snapshot fastapi-backend/cfn_swagger.json —
# regen is deterministic and needs no running CFN. Pass CFN_URL to refresh the
# snapshot from a live instance first.
#
# Writes:
#   fastapi-backend/cfn_swagger.json          (Swagger 2.0 snapshot)
#   fastapi-backend/ioc_cfn_svc_api_client/   (generated typed client)
#
# Usage:
#   scripts/gen-cfn-client.sh
#       Regenerate the client from the committed swagger snapshot.
#   CFN_URL=http://localhost:9002 scripts/gen-cfn-client.sh
#       Refresh the snapshot from a running CFN, then regenerate.
#
# Drift check (CI-able without a stack): regenerate from the committed snapshot
# and `git diff --exit-code` the client. Separately, refresh from upstream
# (CFN_URL or the ioc-cfn-svc repo's docs/swagger.json) and diff the snapshot to
# detect that the CFN's contract moved.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

SNAPSHOT="$ROOT/fastapi-backend/cfn_swagger.json"
OAS3=/tmp/cfn-oas3.json
OUT=/tmp/gen-cfn-client
CONFIG=/tmp/cfn-gen-config.yaml

# Optionally refresh the snapshot from a live CFN.
if [[ -n "${CFN_URL:-}" ]]; then
  echo "→ Refreshing swagger snapshot from $CFN_URL/docs/swagger.json"
  if ! curl -sfL "$CFN_URL/docs/swagger.json" -o "$SNAPSHOT"; then
    echo "✗ Could not reach $CFN_URL/docs/swagger.json" >&2
    exit 1
  fi
fi

if [[ ! -f "$SNAPSHOT" ]]; then
  echo "✗ No swagger snapshot at $SNAPSHOT (run once with CFN_URL set)" >&2
  exit 1
fi

echo "→ Converting Swagger 2.0 → OpenAPI 3"
npx -y swagger2openapi@7 "$SNAPSHOT" -o "$OAS3" >/dev/null

echo "→ Generating client at $OUT"
printf 'package_name_override: ioc_cfn_svc_api_client\n' > "$CONFIG"
rm -rf "$OUT"
(cd "$ROOT/fastapi-backend" && uv run --with openapi-python-client openapi-python-client generate \
  --path "$OAS3" --output-path "$OUT" --config "$CONFIG") >/dev/null

echo "→ Copying to fastapi-backend/ioc_cfn_svc_api_client/"
rm -rf "$ROOT/fastapi-backend/ioc_cfn_svc_api_client"
cp -R "$OUT/ioc_cfn_svc_api_client" "$ROOT/fastapi-backend/"

# Excluded from ruff via extend-exclude, but keep committed output readable.
echo "→ Running ruff format on generated files"
(cd "$ROOT/fastapi-backend" && uv run ruff format --config 'extend-exclude=[]' ioc_cfn_svc_api_client >/dev/null) || true

echo "✓ Done. Run \`git diff\` to see drift."
