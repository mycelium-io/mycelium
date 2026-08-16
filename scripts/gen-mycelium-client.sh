#!/usr/bin/env bash
# Regenerate the Mycelium backend OpenAPI client.
#
# Pulls /openapi.json from a running backend and runs openapi-python-client,
# replacing the committed copies in:
#   - mycelium-client/                     (standalone package, has pyproject.toml)
#   - mycelium-cli/src/mycelium_backend_client/  (vendored copy the CLI imports)
#
# The generated client is NOT committed (see #613); it's a build artifact. CI,
# the wheel/binary builds, and dev setup all run this to materialize it.
#
# Usage:
#   SPEC_FILE=openapi.json scripts/gen-mycelium-client.sh
#       Generate from the committed spec — no backend needed (CI / build / dev).
#       SPEC_FILE is resolved relative to the repo root.
#   scripts/gen-mycelium-client.sh
#       Fetch the spec from a live backend (BACKEND_URL, default localhost:8000)
#       — the path for refreshing after backend changes.
#
# Exit codes:
#   0 — generated.
#   non-zero — generation failed; the client is left as-is.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
SPEC=/tmp/mycelium-openapi.json
OUT=/tmp/gen-mycelium-client

if [ -n "${SPEC_FILE:-}" ]; then
  case "$SPEC_FILE" in
    /*) SPEC="$SPEC_FILE" ;;
    *)  SPEC="$ROOT/$SPEC_FILE" ;;
  esac
  if [ ! -f "$SPEC" ]; then
    echo "✗ SPEC_FILE not found: $SPEC" >&2
    exit 1
  fi
  echo "→ Using committed spec $SPEC"
else
  echo "→ Fetching openapi.json from $BACKEND_URL"
  if ! curl -sfL "$BACKEND_URL/openapi.json" -o "$SPEC"; then
    echo "✗ Could not reach $BACKEND_URL/openapi.json" >&2
    echo "  Start the backend first: docker compose -f mycelium-cli/src/mycelium/docker/compose.yml up -d mycelium-backend" >&2
    exit 1
  fi
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

# Format with the project's ruff config so the output matches what the CLI's
# `ruff format --check src/` gate accepts. Skippable (SKIP_FORMAT=1) for the
# wheel/binary builds, which don't lint — the generator's own formatting is
# enough there and skipping avoids syncing the CLI env just to format.
if [ -z "${SKIP_FORMAT:-}" ]; then
  echo "→ Running ruff format on generated files"
  (cd "$ROOT/mycelium-cli" && uv run ruff format src/mycelium_backend_client >/dev/null) || true
  # mycelium-client/ is a standalone package; format under the cli's ruff config.
  (cd "$ROOT/mycelium-cli" && uv run ruff format ../mycelium-client/mycelium_backend_client >/dev/null) || true
fi

echo "✓ Done."
