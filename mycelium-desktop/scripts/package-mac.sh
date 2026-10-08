#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Sign the built app, notarize it, and wrap it in the disk image people download.
#
# Signing: every program inside the app is signed, innermost first, then the
# app itself. The app carries programs added after it was built, which leaves
# its signature describing a bundle that no longer exists, and macOS calls
# such an app "damaged" and won't open it.
#
# SIGN_IDENTITY is a Developer ID Application certificate in the keychain
# (its name or SHA-1). Signed with one, each program runs under the hardened
# runtime with src-tauri/programs.entitlements, which notarization requires.
# Without one it signs ad hoc ("-"), and the app opens only after the person
# approves it in Privacy & Security.
#
# Notarizing: with APPLE_API_KEY (the path of an App Store Connect API key,
# .p8), APPLE_API_KEY_ID and APPLE_API_ISSUER, the app and then the disk image
# go to Apple and come back with a ticket stapled on, so macOS opens them
# without asking, offline too.
#
# The disk image is made with dmgbuild, which writes the window's layout
# (background, icon positions) itself instead of scripting Finder.
#
# Usage: bash scripts/package-mac.sh [out.dmg]
# Run after: npx tauri build --bundles app --config src-tauri/tauri.bundle.conf.json
# APP overrides the app to package.

set -euo pipefail
# `file` describes some bundled files (fonts) with bytes that aren't valid
# UTF-8; awk in a UTF-8 locale dies on them and cuts the program list short.
export LC_ALL=C

here="$(cd "$(dirname "$0")/.." && pwd)"
app="${APP:-$here/src-tauri/target/release/bundle/macos/Mycelium.app}"
out="${1:-$here/src-tauri/target/release/bundle/dmg/Mycelium-macos-arm64.dmg}"
identity="${SIGN_IDENTITY:--}"
entitlements="$here/src-tauri/programs.entitlements"

if [ ! -d "$app" ]; then
  echo "no app at $app; build it first" >&2
  exit 1
fi

if [ "$identity" = "-" ]; then
  signing=(--force --sign - --timestamp=none)
else
  signing=(--force --sign "$identity" --timestamp --options runtime)
fi
notarizing=0
if [ "$identity" != "-" ] && [ -n "${APPLE_API_KEY:-}" ]; then
  notarizing=1
  apple=(--key "$APPLE_API_KEY" --key-id "${APPLE_API_KEY_ID:?}" --issuer "${APPLE_API_ISSUER:?}")
fi

# Send a file to Apple and wait; stop with Apple's log when it isn't accepted.
notarize() {
  local result status id
  result="$(xcrun notarytool submit "$1" "${apple[@]}" --wait --output-format json || true)"
  status="$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || true)"
  if [ "$status" != "Accepted" ]; then
    echo "Apple didn't accept $(basename "$1"): ${status:-no answer}" >&2
    echo "$result" >&2
    id="$(printf '%s' "$result" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))' 2>/dev/null || true)"
    [ -n "$id" ] && xcrun notarytool log "$id" "${apple[@]}" >&2
    exit 1
  fi
}

echo "signing the programs inside the app…"
# Deepest paths first, so anything that contains code is signed after it.
# Executables carry the entitlements; libraries don't take any.
find "$app/Contents" -type f -print0 \
  | xargs -0 file --no-pad \
  | awk -F': ' '/Mach-O/ { kind = ($2 ~ /executable/) ? "exe" : "lib"; print gsub("/", "/", $1) "\t" kind "\t" $1 }' \
  | sort -rn \
  | cut -f2- \
  | while IFS=$'\t' read -r kind program; do
      if [ "$kind" = exe ] && [ "$identity" != "-" ]; then
        codesign "${signing[@]}" --entitlements "$entitlements" "$program"
      else
        codesign "${signing[@]}" "$program"
      fi
    done

echo "signing the app…"
codesign "${signing[@]}" "$app"
codesign --verify --deep --strict "$app"
echo "signature verified"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
if [ "$notarizing" = 1 ]; then
  echo "notarizing the app (a few minutes)…"
  ditto -c -k --keepParent "$app" "$tmp/Mycelium.zip"
  notarize "$tmp/Mycelium.zip"
  xcrun stapler staple "$app"
fi

echo "making the disk image…"
mkdir -p "$(dirname "$out")"
rm -f "$out"
uv run --with dmgbuild dmgbuild \
  -s "$here/scripts/dmg-settings.py" \
  -D app="$app" \
  -D background="$here/src-tauri/dmg/background.png" \
  Mycelium "$out"
if [ "$identity" != "-" ]; then
  codesign --force --sign "$identity" --timestamp "$out"
fi
if [ "$notarizing" = 1 ]; then
  echo "notarizing the disk image…"
  notarize "$out"
  xcrun stapler staple "$out"
fi
echo "made $out"

# The in-app updater's half: the signed app as an archive, signed with the
# updater key, and its manifest (scripts/updater.sh). Without the key (a
# local build) this is skipped.
source "$here/scripts/updater.sh"
[ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ] || { echo "no TAURI_SIGNING_PRIVATE_KEY; skipping the update archive"; exit 0; }
outdir="$(dirname "$out")"
archive="$outdir/Mycelium-macos-arm64.app.tar.gz"
echo "making the update archive…"
rm -f "$archive"
COPYFILE_DISABLE=1 tar -czf "$archive" -C "$(dirname "$app")" "$(basename "$app")"
updater_manifest "$archive" darwin-aarch64
