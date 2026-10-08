#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Build Mycelium for Linux: one AppImage, the app and everything it carries
# (stage-sidecars.sh) in a single file that runs on any recent distribution
# without installing. An AppImage is also the Linux format Tauri's updater
# can replace in place. No .deb: the app carries its own node, which a
# package would install as /usr/bin/node over the distribution's.
#
# Inside it the layout is usr/bin (the app and its programs) beside
# usr/lib/Mycelium (hub/, ui/, models/, pi/), which is where the supervisor
# and the Pi launcher look.
#
# Needs FUSE-less tooling only (the AppImages it runs unpack themselves),
# and downloads appimagetool and the AppImage runtime, pinned by hash.
#
# Needs Tauri's Linux build dependencies (webkit2gtk 4.1 and friends; see
# https://v2.tauri.app/start/prerequisites/#linux).
#
# Usage: bash scripts/package-linux.sh [out.AppImage]
# Run after: bash scripts/stage-sidecars.sh

set -euo pipefail

here="$(cd "$(dirname "$0")/.." && pwd)"
arch="$(uname -m)"
out="${1:-$here/src-tauri/target/release/bundle/Mycelium-linux-$arch.AppImage}"
if [ "$arch" != x86_64 ]; then
  echo "only x86_64 is packaged so far" >&2
  exit 1
fi

# appimagetool and the AppImage runtime, pinned and checked.
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
APPIMAGETOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"

# linuxdeploy and appimagetool are themselves AppImages; without FUSE (a
# container, a CI runner) they have to unpack themselves to run.
export APPIMAGE_EXTRACT_AND_RUN=1
# linuxdeploy's own strip predates the sections newer toolchains write, and
# fails on them; the programs that are worth stripping were stripped when staged.
export NO_STRIP=1

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fetch() {
  curl -fsSL "$1" -o "$tmp/$3"
  echo "$2  $tmp/$3" | sha256sum -c --quiet
  chmod +x "$tmp/$3"
}

# Tauri builds the AppImage with linuxdeploy, which walks every program and
# library in it to bring along what each needs, and rewrites their library
# paths. The hub (a PyInstaller build) already carries its own, under names
# linuxdeploy can't resolve, and a rewritten herdr (static-pie) crashes. So
# the AppImage is built without the hub, then the hub and the programs the
# app carries are put in as they were staged.
cd "$here"
# Tauri adds to an AppDir left from an earlier build rather than starting over.
rm -rf src-tauri/target/release/bundle/appimage src-tauri/target/release/bundle/appimage_deb
# The bundle config less the hub (a merged config can add keys, not drop them).
without_hub="$(node -e '
  const c = require("./src-tauri/tauri.bundle.conf.json");
  delete c.bundle.resources["resources/hub/"];
  process.stdout.write(JSON.stringify(c));
')"
npx tauri build --bundles appimage --config "$without_hub"
built="$(ls -t src-tauri/target/release/bundle/appimage/*.AppImage 2>/dev/null | head -n 1)"
if [ -z "$built" ]; then
  echo "tauri build made no AppImage" >&2
  exit 1
fi

echo "adding the hub and the programs…"
(cd "$tmp" && "$here/$built" --appimage-extract >/dev/null)
cp -R src-tauri/resources/hub "$tmp/squashfs-root/usr/lib/Mycelium/hub"
for program in mycelium herdr slimctl node; do
  cp "src-tauri/binaries/$program-$(rustc --print host-tuple)" "$tmp/squashfs-root/usr/bin/$program"
done
fetch "$APPIMAGETOOL_URL" "$APPIMAGETOOL_SHA256" appimagetool
fetch "$RUNTIME_URL" "$RUNTIME_SHA256" runtime
mkdir -p "$(dirname "$out")"
rm -f "$out"
ARCH=x86_64 "$tmp/appimagetool" --no-appstream --runtime-file "$tmp/runtime" \
  "$tmp/squashfs-root" "$out" >/dev/null
chmod +x "$out"
echo "made $out"

source "$here/scripts/updater.sh"
updater_manifest "$out" "linux-$arch"
