#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Sign the built app and wrap it in the disk image people download.
#
# Signing: every program inside the app is signed, innermost first, then the
# app itself. The app carries programs added after it was built, which leaves
# its signature describing a bundle that no longer exists, and macOS calls
# such an app "damaged" and won't open it. Signed as a whole, it opens like
# any app from an unidentified developer: the person approves it once.
# SIGN_IDENTITY defaults to "-" (ad-hoc); set it to a Developer ID to sign
# for real, which is what notarization will need.
#
# The disk image is made with dmgbuild, which writes the window's layout
# (background, icon positions) itself instead of scripting Finder.
#
# Usage: bash scripts/package-mac.sh [out.dmg]
# Run after: npx tauri build --bundles app --config src-tauri/tauri.bundle.conf.json

set -euo pipefail
# `file` describes some bundled files (fonts) with bytes that aren't valid
# UTF-8; awk in a UTF-8 locale dies on them and cuts the program list short.
export LC_ALL=C

here="$(cd "$(dirname "$0")/.." && pwd)"
app="$here/src-tauri/target/release/bundle/macos/Mycelium.app"
out="${1:-$here/src-tauri/target/release/bundle/dmg/Mycelium-macos-arm64.dmg}"
identity="${SIGN_IDENTITY:--}"

if [ ! -d "$app" ]; then
  echo "no app at $app; build it first" >&2
  exit 1
fi

echo "signing the programs inside the app…"
# Deepest paths first, so anything that contains code is signed after it.
find "$app/Contents" -type f -print0 \
  | xargs -0 file --no-pad \
  | awk -F': ' '/Mach-O/ { print $1 }' \
  | awk '{ print gsub("/", "/") "\t" $0 }' \
  | sort -rn \
  | cut -f2- \
  | while IFS= read -r program; do
      codesign --force --sign "$identity" --timestamp=none "$program"
    done

echo "signing the app…"
codesign --force --sign "$identity" --timestamp=none "$app"
codesign --verify --deep --strict "$app"
echo "signature verified"

echo "making the disk image…"
mkdir -p "$(dirname "$out")"
rm -f "$out"
uv run --with dmgbuild dmgbuild \
  -s "$here/scripts/dmg-settings.py" \
  -D app="$app" \
  -D background="$here/src-tauri/dmg/background.png" \
  Mycelium "$out"
echo "made $out"

# The in-app updater's half: the signed app as an archive, signed with the
# updater key, and latest.json naming it. The app checks latest.json on the
# latest release and installs the archive only if its signature matches the
# public key it was built with. Without the key (a local build) this is skipped.
if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
  echo "no TAURI_SIGNING_PRIVATE_KEY; skipping the update archive"
  exit 0
fi
outdir="$(dirname "$out")"
archive="$outdir/Mycelium-macos-arm64.app.tar.gz"
tag="${RELEASE_TAG:-${GITHUB_REF_NAME:?set RELEASE_TAG to the release tag}}"
version="$(sed -nE 's/^  "version": "([^"]+)".*/\1/p' "$here/src-tauri/tauri.conf.json")"

echo "making the update archive…"
rm -f "$archive" "$archive.sig"
COPYFILE_DISABLE=1 tar -czf "$archive" -C "$(dirname "$app")" Mycelium.app
# Reads the key and its password from TAURI_SIGNING_PRIVATE_KEY(_PASSWORD).
(cd "$here" && npx tauri signer sign "$archive" >/dev/null)

python3 - "$outdir/latest.json" "$version" "$(cat "$archive.sig")" \
  "https://github.com/mycelium-io/mycelium/releases/download/$tag/$(basename "$archive")" <<'PY'
import datetime, json, sys
path, version, signature, url = sys.argv[1:]
json.dump({
    "version": version,
    "pub_date": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "platforms": {"darwin-aarch64": {"signature": signature, "url": url}},
}, open(path, "w"), indent=2)
PY
echo "made $archive and latest.json ($version)"
