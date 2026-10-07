#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Stage everything the Mycelium app carries, so it runs with nothing else
# installed: on a Mac (Mycelium.app), on Linux (an AppImage) or on Windows
# (an installer). Runs on the platform it stages for; on Windows, in Git Bash.
#
# Programs, into src-tauri/binaries as <name>-<target triple>[.exe] (Tauri's
# externalBin, which lands beside the app's own executable: Contents/MacOS,
# usr/bin, or the install folder):
#
#   mycelium  the CLI and the supervisor (PyInstaller, as the release builds it)
#   herdr     pinned release; where agents run
#   slimctl   pinned 2.1.x; the SLIM node. It has to match the slim-bindings
#             the hub speaks, or the handshake fails
#   node      runs the UI server and Pi
#
# Directories, into src-tauri/resources (Contents/Resources on a Mac,
# usr/lib/Mycelium in an AppImage, the install folder on Windows):
#
#   hub/      the hub, a PyInstaller directory build
#   ui/       the UI's standalone build, with its static files
#   models/   the embedding model, so memory search works offline
#   pi/       Pi, which the engines think with, and a launcher that runs it
#             on the bundled node (pi, or pi.cmd on Windows)
#   conpty/   Windows only: the console host herdr runs its panes in
#
# Usage: bash scripts/stage-sidecars.sh [step...]
#   steps: herdr slimctl node mycelium hub models ui pi (default: all)
# Overrides: MYCELIUM_BIN (a prebuilt CLI), NODE_BIN (a node to copy)

set -euo pipefail

# At least mycelium.integrations.herdr.bridge.MIN_VERSION.
HERDR_TAG="v0.9.3"
SLIMCTL_TAG="slimctl-v2.1.1"
NODE_VERSION="24.19.0"
PI_VERSION="0.87.1"
EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"

here="$(cd "$(dirname "$0")/.." && pwd)"
repo="$(cd "$here/.." && pwd)"
bin="$here/src-tauri/binaries"
res="$here/src-tauri/resources"
work="$here/src-tauri/target/stage"
triple="$(rustc --print host-tuple)"
mkdir -p "$bin" "$res" "$work"

# Per target: herdr's and slimctl's release assets, node's build, and the
# esbuild package Pi needs (esbuild names Windows win32, node names it win).
x=""
case "$triple" in
  aarch64-apple-darwin) os=mac; herdr_asset="herdr-macos-aarch64"; slim_asset="slimctl-darwin-arm64.tar.gz"; node_arch="darwin-arm64"; esbuild_arch="darwin-arm64" ;;
  x86_64-apple-darwin) os=mac; herdr_asset="herdr-macos-x86_64"; slim_asset="slimctl-darwin-amd64.tar.gz"; node_arch="darwin-x64"; esbuild_arch="darwin-x64" ;;
  x86_64-unknown-linux-gnu) os=linux; herdr_asset="herdr-linux-x86_64"; slim_asset="slimctl-linux-amd64-gnu.tar.gz"; node_arch="linux-x64"; esbuild_arch="linux-x64" ;;
  aarch64-unknown-linux-gnu) os=linux; herdr_asset="herdr-linux-aarch64"; slim_asset="slimctl-linux-arm64-gnu.tar.gz"; node_arch="linux-arm64"; esbuild_arch="linux-arm64" ;;
  x86_64-pc-windows-msvc) os=windows; x=".exe"; herdr_asset="herdr-windows-x86_64.zip"; slim_asset="slimctl-windows-amd64.zip"; node_arch="win-x64"; esbuild_arch="win32-x64" ;;
  *) echo "no pinned builds for $triple" >&2; exit 1 ;;
esac

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

place() { cp "$1" "$bin/$2-$triple$x"; chmod +x "$bin/$2-$triple$x"; echo "staged $2"; }

# A release asset, downloaded over plain HTTPS so no GitHub login is needed.
fetch() { curl -fsSL "https://github.com/$1/releases/download/$2/$3" -o "$tmp/$3"; }

# Unpack an archive into $tmp: zips on Windows, tarballs elsewhere.
unpack() {
  case "$1" in
    *.zip) unzip -q -o "$tmp/$1" -d "$tmp/${1%.zip}" ;;
    *) tar -xzf "$tmp/$1" -C "$tmp" ;;
  esac
}

# On a Mac, drop a program's debug symbols (a fifth of node, a sixth of
# slimctl), then sign it ad hoc again: stripping breaks its signature, and
# macOS won't run an arm64 program without a valid one. package-mac.sh signs
# it for real. Never the mycelium CLI: its code is an archive appended to the
# program, which strip cuts off. Linux and Windows builds come stripped
# already, and stripping herdr's static-pie Linux build again breaks it.
strip_program() {
  [ "$os" = mac ] || return 0
  # strip warns that the signature is now invalid; it is signed again below.
  strip -x "$bin/$1-$triple" 2>/dev/null
  codesign --force --sign - "$bin/$1-$triple" 2>/dev/null
}

stage_herdr() {
  fetch herdrdev/herdr "$HERDR_TAG" "$herdr_asset"
  if [ "$os" = windows ]; then
    # herdr runs its panes in the ConPTY console host it ships beside it.
    unpack "$herdr_asset"
    place "$tmp/${herdr_asset%.zip}/herdr.exe" herdr
    rm -rf "$res/conpty" && cp -R "$tmp/${herdr_asset%.zip}/conpty" "$res/conpty"
    return
  fi
  place "$tmp/$herdr_asset" herdr
  strip_program herdr
}

stage_slimctl() {
  fetch agntcy/slim "$SLIMCTL_TAG" "$slim_asset"
  unpack "$slim_asset"
  place "$(find "$tmp" -type f -name "slimctl$x" | head -n 1)" slimctl
  strip_program slimctl
}

stage_node() {
  if [ -n "${NODE_BIN:-}" ]; then
    place "$NODE_BIN" node
    return
  fi
  local node_dir="node-v$NODE_VERSION-$node_arch"
  if [ "$os" = windows ]; then
    curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/$node_dir.zip" -o "$tmp/node.zip"
    unzip -q "$tmp/node.zip" "$node_dir/node.exe" -d "$tmp"
    place "$tmp/$node_dir/node.exe" node
    return
  fi
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/$node_dir.tar.gz" -o "$tmp/node.tar.gz"
  tar -xzf "$tmp/node.tar.gz" -C "$tmp" "$node_dir/bin/node"
  place "$tmp/$node_dir/bin/node" node
  strip_program node
}

# Copy a directory, following links and leaving out the names given. Python,
# not rsync, which Git Bash on Windows doesn't have.
copy_tree() {
  local src="$1" dst="$2"
  shift 2
  uv run --no-project python -c '
import shutil, sys
src, dst, *skip = sys.argv[1:]
shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*skip), dirs_exist_ok=True)
' "$src" "$dst" "$@"
}

# A virtualenv's own programs: bin/ everywhere but Windows, which has Scripts/.
venv_bin() {
  if [ "$os" = windows ]; then echo "$1/Scripts/$2.exe"; else echo "$1/bin/$2"; fi
}

client_built=""
openapi_client() {
  [ -n "$client_built" ] && return
  (
    cd "$repo"
    SPEC_FILE=openapi.json SKIP_FORMAT=1 bash scripts/gen-mycelium-client.sh
    cd mycelium-client && uv build --wheel
  )
  client_built=1
}

stage_mycelium() {
  if [ -n "${MYCELIUM_BIN:-}" ]; then
    place "$MYCELIUM_BIN" mycelium
    return
  fi
  openapi_client
  echo "building mycelium…"
  (
    cd "$repo/mycelium-cli"
    uv venv "$work/cli-venv" --allow-existing
    uv pip install --python "$(venv_bin "$work/cli-venv" python)" -e . ../mycelium-client/dist/*.whl pyinstaller
    "$(venv_bin "$work/cli-venv" pyinstaller)" --noconfirm --onefile --name mycelium \
      --collect-all mycelium --collect-all pyfiglet \
      --hidden-import mycelium_backend_client \
      --distpath "$work/cli-dist" --workpath "$work/cli-build" --specpath "$work" \
      -p src src/mycelium/cli.py
  )
  place "$work/cli-dist/mycelium$x" mycelium
}

stage_hub() {
  echo "building the hub…"
  # NEGMAS depends on a data-science stack the aligner never loads (pyarrow
  # alone is 200 MB with its libraries). Left out; the backend's whole suite
  # passes with these imports blocked. plotly stays: NEGMAS imports it when an
  # agent joins a negotiation.
  local unused=(pyarrow pandas scipy sklearn matplotlib gif)
  (
    cd "$repo/fastapi-backend"
    uv run --with pyinstaller pyinstaller --noconfirm --onedir --name mycelium-hub \
      --distpath "$work/hub-dist" --workpath "$work/hub-build" --specpath "$work" \
      "${unused[@]/#/--exclude-module=}" \
      --collect-all fastembed --collect-all onnxruntime --collect-all slim_bindings \
      --collect-all negmas --collect-all tokenizers --collect-submodules app \
      --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto \
      --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto \
      --hidden-import uvicorn.lifespan.on \
      --add-data "$repo/fastapi-backend/pyproject.toml:." \
      hub_entry.py
  )
  rm -rf "$res/hub" && cp -R "$work/hub-dist/mycelium-hub" "$res/hub"
  echo "staged hub"
}

stage_models() {
  rm -rf "$res/models" && mkdir -p "$res/models"
  (
    cd "$repo/fastapi-backend"
    uv run python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='$EMBEDDING_MODEL', cache_dir='$tmp/models')"
  )
  # The download is a Hugging Face cache: the files in blobs/, and links to
  # them in snapshots/. The app bundle turns links into copies, which would
  # carry the model twice; the snapshot's files alone are what loads it.
  copy_tree "$tmp/models" "$res/models" blobs
  echo "staged the embedding model"
}

stage_ui() {
  echo "building the UI…"
  # Built from its own copy with a clean npm install. npm's node_modules is
  # plain folders; pnpm's is symlinks into .pnpm, which neither survives the
  # app bundle (it drops symlinks) nor flattening (Next's standalone output
  # leaves stub packages at the top that resolve to nothing). A copy also
  # leaves the working tree's node_modules and .next alone.
  # Outside the repo: inside it, Next takes the nearest package.json above
  # as the workspace root and nests server.js under that path.
  local src="$tmp/mycelium-frontend"
  rm -rf "$src" && mkdir -p "$src"
  # screenshots/ is repo tooling that reaches outside the frontend (../../shotkit).
  copy_tree "$repo/mycelium-frontend" "$src" node_modules .next screenshots
  (
    cd "$src"
    npm ci --no-audit --no-fund
    npm run build
  )
  rm -rf "$res/ui" && mkdir -p "$res/ui/.next"
  cp -R "$src/.next/standalone/." "$res/ui/"
  cp -R "$src/.next/static" "$res/ui/.next/static"
  cp -R "$src/public" "$res/ui/public"
  if find "$res/ui/node_modules" -type l | grep -q .; then
    echo "the UI's node_modules has symlinks, which the app bundle drops" >&2
    exit 1
  fi
  echo "staged ui"
}

stage_pi() {
  rm -rf "$res/pi" && mkdir -p "$res/pi"
  npm install --prefix "$res/pi" --omit=dev --no-audit --no-fund --no-package-lock \
    "@earendil-works/pi-coding-agent@$PI_VERSION"
  # Pi's lockfile pulls esbuild's native binary for every platform (~290 MB);
  # this platform needs its own.
  find "$res/pi/node_modules" -type d -path "*/@esbuild/*" -prune ! -name "$esbuild_arch" -exec rm -rf {} +
  # Half of what is left is for building against Pi, not running it: source
  # maps, type declarations, and npm's .bin shims (copies, once in the bundle).
  find "$res/pi/node_modules" -type f \
    \( -name "*.map" -o -name "*.d.ts" -o -name "*.d.mts" -o -name "*.d.cts" \) -delete
  find "$res/pi/node_modules" -type d -name .bin -prune -exec rm -rf {} +
  # The hub runs `pi` as a program; this is that program, on the app's node,
  # which sits where the app's programs do: from pi/, Contents/MacOS on a
  # Mac, usr/bin in an AppImage, and the install folder on Windows.
  local cli='node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js'
  if [ "$os" = windows ]; then
    printf '@"%%~dp0..\\node.exe" "%%~dp0%s" %%*\r\n' "${cli//\//\\}" > "$res/pi/pi.cmd"
  else
    local node='../../MacOS/node'
    [ "$os" = linux ] && node='../../../bin/node'
    cat > "$res/pi/pi" <<LAUNCHER
#!/bin/sh
here="\$(cd "\$(dirname "\$0")" && pwd)"
exec "\$here/$node" "\$here/$cli" "\$@"
LAUNCHER
    chmod +x "$res/pi/pi"
  fi
  echo "staged pi $PI_VERSION"
}

steps=("$@")
[ ${#steps[@]} -eq 0 ] && steps=(herdr slimctl node mycelium hub models ui pi)
for step in "${steps[@]}"; do
  "stage_$step"
done

du -sh "$bin"/* "$res"/* 2>/dev/null || true
