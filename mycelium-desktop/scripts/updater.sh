# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# The in-app updater's half of packaging, shared by package-mac.sh,
# package-linux.sh and package-windows.sh (sourced, not run).
#
# updater_manifest FILE PLATFORM signs FILE with the updater key and writes
# updater-PLATFORM.json beside it: a latest.json naming this one platform.
# The release merges every platform's into the one latest.json the app reads
# (releases/latest/download/latest.json), and installs FILE only if its
# signature matches the public key the app was built with.
#
# Reads the key and its password from TAURI_SIGNING_PRIVATE_KEY(_PASSWORD),
# and the release tag from RELEASE_TAG or GITHUB_REF_NAME. Without the key (a
# local build) it says so and returns 1, which a caller takes as "skip".

updater_manifest() {
  local file="$1" platform="$2"
  if [ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
    echo "no TAURI_SIGNING_PRIVATE_KEY; skipping the update manifest"
    return 1
  fi
  local here tag version outdir
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  tag="${RELEASE_TAG:-${GITHUB_REF_NAME:?set RELEASE_TAG to the release tag}}"
  version="$(sed -nE 's/^  "version": "([^"]+)".*/\1/p' "$here/src-tauri/tauri.conf.json")"
  outdir="$(cd "$(dirname "$file")" && pwd)"

  rm -f "$file.sig"
  (cd "$here" && npx tauri signer sign "$file" >/dev/null)
  # node, not python: it is on every machine that just ran tauri build.
  node -e '
    const [path, version, platform, signature, url] = process.argv.slice(1);
    const pub_date = new Date().toISOString().replace(/\.\d+Z$/, "Z");
    require("fs").writeFileSync(path, JSON.stringify(
      { version, pub_date, platforms: { [platform]: { signature, url } } }, null, 2));
  ' "$outdir/updater-$platform.json" "$version" "$platform" "$(cat "$file.sig")" \
    "https://github.com/mycelium-io/mycelium/releases/download/$tag/$(basename "$file")"
  echo "made the update manifest for $platform ($version)"
}
