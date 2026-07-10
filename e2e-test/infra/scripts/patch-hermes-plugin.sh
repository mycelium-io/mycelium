#!/usr/bin/env bash
# Infra-side patches for the staged hermes mycelium plugin in compose labs.
#
# Keeps product mycelium-cli unchanged while unblocking known container issues:
#   - hermes gateway passes ``is_reconnect`` to ``connect()`` (newer hermes-agent)
#   - aiohttp is installed in Dockerfile.spoke; this script is a no-op for that

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-${HOME}/.hermes}"
ADAPTER="${HERMES_HOME}/plugins/mycelium/adapter.py"

if [ ! -f "$ADAPTER" ]; then
    echo "[patch-hermes-plugin] no adapter at ${ADAPTER} — skipping" >&2
    exit 0
fi

if grep -q 'is_reconnect: bool = False' "$ADAPTER"; then
    echo "[patch-hermes-plugin] adapter already patched"
    exit 0
fi

python3 - "$ADAPTER" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = "    async def connect(self) -> bool:"
new = "    async def connect(self, *, is_reconnect: bool = False) -> bool:  # noqa: ARG002"
if old not in text:
    raise SystemExit(f"[patch-hermes-plugin] connect() signature not found in {path}")
path.write_text(text.replace(old, new, 1))
print(f"[patch-hermes-plugin] patched {path}")
PY
