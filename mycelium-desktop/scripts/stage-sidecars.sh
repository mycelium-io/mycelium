#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Stage everything Mycelium.app carries, so it runs on a Mac with nothing
# else installed.
#
# Programs, into src-tauri/binaries as <name>-<target triple> (Tauri's
# externalBin, which lands in Contents/MacOS):
#
#   mycelium  the CLI and the supervisor (PyInstaller, as the release builds it)
#   herdr     pinned release; where agents run
#   slimctl   pinned 2.1.x; the SLIM node. It has to match the slim-bindings
#             the hub speaks, or the handshake fails
#   node      runs the UI server and Pi
#
# Directories, into src-tauri/resources (Contents/Resources):
#
#   hub/      the hub, a PyInstaller directory build
#   ui/       the UI's standalone build, with its static files
#   models/   the embedding model, so memory search works offline
#   pi/       Pi, which the engines think with, and a launcher that runs it
#             on the bundled node
#
# Usage: bash scripts/stage-sidecars.sh [step...]
#   steps: herdr slimctl node mycelium hub models ui pi (default: all)
# Overrides: MYCELIUM_BIN (a prebuilt CLI), NODE_BIN (a node to copy)

set -euo pipefail

HERDR_TAG="v0.9.1"
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

case "$triple" in
  aarch64-apple-darwin) herdr_asset="herdr-macos-aarch64"; slim_asset="slimctl-darwin-arm64.tar.gz"; node_arch="darwin-arm64" ;;
  x86_64-apple-darwin) herdr_asset="herdr-macos-x86_64"; slim_asset="slimctl-darwin-amd64.tar.gz"; node_arch="darwin-x64" ;;
  *) echo "no pinned builds for $triple" >&2; exit 1 ;;
esac

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

place() { cp "$1" "$bin/$2-$triple"; chmod +x "$bin/$2-$triple"; echo "staged $2"; }

stage_herdr() {
  gh release download "$HERDR_TAG" -R herdrdev/herdr -p "$herdr_asset" -D "$tmp"
  place "$tmp/$herdr_asset" herdr
}

stage_slimctl() {
  gh release download "$SLIMCTL_TAG" -R agntcy/slim -p "$slim_asset" -D "$tmp"
  tar -xzf "$tmp/$slim_asset" -C "$tmp"
  place "$(find "$tmp" -type f -name slimctl | head -n 1)" slimctl
}

stage_node() {
  if [ -n "${NODE_BIN:-}" ]; then
    place "$NODE_BIN" node
    return
  fi
  local node_dir="node-v$NODE_VERSION-$node_arch"
  curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/$node_dir.tar.gz" -o "$tmp/node.tar.gz"
  tar -xzf "$tmp/node.tar.gz" -C "$tmp" "$node_dir/bin/node"
  place "$tmp/$node_dir/bin/node" node
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
    uv pip install --python "$work/cli-venv/bin/python" -e . ../mycelium-client/dist/*.whl pyinstaller
    "$work/cli-venv/bin/pyinstaller" --noconfirm --onefile --name mycelium \
      --collect-all mycelium --collect-all pyfiglet \
      --hidden-import mycelium_backend_client \
      --distpath "$work/cli-dist" --workpath "$work/cli-build" --specpath "$work" \
      -p src src/mycelium/cli.py
  )
  place "$work/cli-dist/mycelium" mycelium
}

stage_hub() {
  echo "building the hub…"
  (
    cd "$repo/fastapi-backend"
    uv run --with pyinstaller pyinstaller --noconfirm --onedir --name mycelium-hub \
      --distpath "$work/hub-dist" --workpath "$work/hub-build" --specpath "$work" \
      --collect-all fastembed --collect-all onnxruntime --collect-all slim_bindings \
      --collect-all negmas --collect-all tokenizers --collect-submodules app \
      --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto \
      --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto \
      --hidden-import uvicorn.lifespan.on \
      hub_entry.py
  )
  rm -rf "$res/hub" && cp -R "$work/hub-dist/mycelium-hub" "$res/hub"
  echo "staged hub"
}

stage_models() {
  rm -rf "$res/models" && mkdir -p "$res/models"
  (
    cd "$repo/fastapi-backend"
    uv run python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='$EMBEDDING_MODEL', cache_dir='$res/models')"
  )
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
  rsync -a --exclude node_modules --exclude .next --exclude screenshots \
    "$repo/mycelium-frontend/" "$src/"
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
  # a Mac needs its own.
  find "$res/pi/node_modules" -type d -path "*/@esbuild/*" -prune ! -name "$node_arch" -exec rm -rf {} +
  # The hub runs `pi` as a program; this is that program, on the app's node.
  cat > "$res/pi/pi" <<'LAUNCHER'
#!/bin/sh
here="$(cd "$(dirname "$0")" && pwd)"
exec "$here/../../MacOS/node" "$here/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js" "$@"
LAUNCHER
  chmod +x "$res/pi/pi"
  echo "staged pi $PI_VERSION"
}

steps=("$@")
[ ${#steps[@]} -eq 0 ] && steps=(herdr slimctl node mycelium hub models ui pi)
for step in "${steps[@]}"; do
  "stage_$step"
done

du -sh "$bin"/* "$res"/* 2>/dev/null || true
