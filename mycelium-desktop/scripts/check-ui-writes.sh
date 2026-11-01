#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Check that the UI server writes nothing into the signed app as it runs.
#
# The UI runs from inside the bundle (Contents/Resources/ui), and anything it
# writes next to itself at run time, like the image optimizer's cache once did,
# breaks the app's signature after its first page: codesign then fails, and so
# can Gatekeeper and the updater's check. This starts the UI from the bundle
# with the app's own node, loads a few pages and the image endpoint, stops it,
# and fails if a file appeared in the bundle or the signature no longer holds.
#
# Usage: bash scripts/check-ui-writes.sh path/to/Mycelium.app
# package-mac.sh runs it on the app it just signed.

set -euo pipefail

app="${1:?usage: check-ui-writes.sh path/to/Mycelium.app}"
ui="$app/Contents/Resources/ui"
node="$app/Contents/MacOS/node"
seal="$app/Contents/_CodeSignature/CodeResources"
[ -f "$ui/server.js" ] && [ -x "$node" ] && [ -f "$seal" ] || {
  echo "no signed app with a UI at $app" >&2
  exit 1
}

port="$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
log="$(mktemp)"
# A backend nobody answers on: the pages render their own way through it, and
# what matters here is what the UI server does on disk.
(cd "$ui" && PORT="$port" HOSTNAME=127.0.0.1 MYCELIUM_INTERNAL_API_URL=http://127.0.0.1:9 \
  exec "$node" server.js) > "$log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; rm -f "$log"' EXIT

for _ in $(seq 1 60); do
  curl -s -o /dev/null "http://127.0.0.1:$port/" && break
  sleep 0.5
done
for path in / /machines /room/check /learn "/_next/image?url=%2Flogo.png&w=64&q=75"; do
  curl -s -o /dev/null "http://127.0.0.1:$port$path" || {
    echo "the UI server didn't answer $path; its output:" >&2
    cat "$log" >&2
    exit 1
  }
done
kill "$pid"
wait "$pid" 2>/dev/null || true

# The UI's own folder: signing writes the app's main program after the seal,
# so the rest of the bundle can be newer than it without anything being wrong.
written="$(find "$ui" -newer "$seal" -type f)"
if [ -n "$written" ]; then
  echo "the UI server wrote into the signed app, which breaks its signature:" >&2
  echo "$written" >&2
  exit 1
fi
codesign --verify --deep --strict "$app"
echo "the UI wrote nothing into the app, and its signature holds"
