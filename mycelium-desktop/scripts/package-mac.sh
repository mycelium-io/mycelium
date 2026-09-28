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
