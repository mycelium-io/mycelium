#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Build Mycelium for Windows: an installer (NSIS) that puts the app and
# everything it carries (stage-sidecars.sh) in the person's own
# %LOCALAPPDATA%\Mycelium, with no administrator prompt, and registers
# mycelium:// links. The installer is also what Tauri's updater runs to
# update in place. Windows keeps resources beside the executable, so hub\,
# ui\, models\, pi\ and conpty\ (herdr's console host) sit next to
# mycelium.exe and herdr.exe.
#
# The installer isn't Authenticode-signed yet, so SmartScreen asks before
# the first run ("More info", then "Run anyway").
#
# Run in Git Bash, after: bash scripts/stage-sidecars.sh
# Usage: bash scripts/package-windows.sh [out-setup.exe]

set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
out="${1:-$here/src-tauri/target/release/bundle/Mycelium-windows-x86_64-setup.exe}"

cd "$here"
npx tauri build --bundles nsis \
  --config src-tauri/tauri.bundle.conf.json \
  --config src-tauri/tauri.bundle.windows.conf.json

built="$(ls -t src-tauri/target/release/bundle/nsis/*-setup.exe 2>/dev/null | head -n 1)"
if [ -z "$built" ]; then
  echo "tauri build made no installer" >&2
  exit 1
fi
mkdir -p "$(dirname "$out")"
cp "$built" "$out"
echo "made $out"

source "$here/scripts/updater.sh"
updater_manifest "$out" windows-x86_64 || true
