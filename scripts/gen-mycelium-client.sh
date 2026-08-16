#!/usr/bin/env bash
# Generate the Mycelium backend OpenAPI clients from the committed spec.
#
# The clients are build artifacts, not source: both trees are gitignored and
# regenerated from openapi.json (the snapshot scripts/snapshot-openapi.sh
# writes). Generating needs no running backend.
#
#   - mycelium-client/mycelium_backend_client/          standalone package
#   - mycelium-cli/src/mycelium_backend_client/         the copy the CLI imports
#
# Usage:
#   scripts/gen-mycelium-client.sh
#       Generate both trees from openapi.json.
#   SPEC=/path/to/openapi.json scripts/gen-mycelium-client.sh
#       Generate from a spec elsewhere.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

SPEC="${SPEC:-$ROOT/openapi.json}"
# Keep in step with the build-system pin in mycelium-cli/pyproject.toml, so the
# script and the CLI's build hook emit the same client.
GENERATOR_VERSION=0.28.3
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT

if [ ! -f "$SPEC" ]; then
  echo "✗ No spec at $SPEC" >&2
  echo "  Write one with: scripts/snapshot-openapi.sh" >&2
  exit 1
fi

echo "→ Generating client from $SPEC"
uv run --no-project --with "openapi-python-client==$GENERATOR_VERSION" openapi-python-client generate \
  --path "$SPEC" --output-path "$OUT/gen" --overwrite >/dev/null

for dest in "$ROOT/mycelium-client" "$ROOT/mycelium-cli/src"; do
  echo "→ Copying to ${dest#"$ROOT"/}/mycelium_backend_client/"
  rm -rf "${dest:?}/mycelium_backend_client"
  cp -R "$OUT/gen/mycelium_backend_client" "$dest/"
done

# Stamp the CLI copy with the spec hash. mycelium-cli/setup.py reads this to
# decide whether a build has to regenerate, so running this script means the
# next build is a no-op instead of a second generation.
uv run --no-project python -c '
import hashlib
import pathlib
import sys

spec, stamp = sys.argv[1:]
pathlib.Path(stamp).write_text(hashlib.sha256(pathlib.Path(spec).read_bytes()).hexdigest() + "\n")
' "$SPEC" "$ROOT/mycelium-cli/src/mycelium_backend_client/.openapi-sha256"

echo "✓ Done."
