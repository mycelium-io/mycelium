#!/usr/bin/env bash
# Bring shotkit/ up to date with the standalone shotkit repo.
#
# shotkit lives at github.com/juliarvalenti/shotkit and is vendored here, so the
# screenshot pipeline and the promo run from a plain checkout with no install
# step. This copies a ref of it over shotkit/ and records which commit it was in
# shotkit/UPSTREAM. Changes go upstream first and arrive here through this
# script; an edit made only here is overwritten on the next sync.
#
# Kept across a sync: shotkit/recordings/ (mycelium's own recording scripts,
# which the standalone repo does not carry) and shotkit/flows/ (mycelium's
# flows, how to get its UI into a state; `shot flows` lists them). Left behind: the repo's LICENSE,
# .gitignore and Claude Code skill (mycelium has its own screenshot skill).
#
# Usage:
#   scripts/sync-shotkit.sh              # the latest main
#   scripts/sync-shotkit.sh <ref>        # a branch, tag or commit
#   SHOTKIT_SRC=~/code/shotkit scripts/sync-shotkit.sh   # a local checkout instead of a clone
#
# Then run its selftest and the frontend typecheck (shotkit's JSDoc is checked
# by mycelium-frontend's tsc, through screenshots/capture.ts):
#   node shotkit/test/selftest.mjs && (cd mycelium-frontend && npx tsc --noEmit)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REF="${1:-main}"
DEST="$ROOT/shotkit"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ -n "${SHOTKIT_SRC:-}" ]; then
  SRC="$SHOTKIT_SRC"
else
  git clone --quiet https://github.com/juliarvalenti/shotkit "$WORK/repo"
  SRC="$WORK/repo"
fi

SHA="$(git -C "$SRC" rev-parse --verify "$REF^{commit}")"
mkdir -p "$WORK/tree"
git -C "$SRC" archive "$SHA" | tar -x -C "$WORK/tree"

rsync -a --delete \
  --exclude '/recordings/' \
  --exclude '/flows/' \
  --exclude '/node_modules/' \
  --exclude '/UPSTREAM' \
  --exclude '/LICENSE' \
  --exclude '/.gitignore' \
  --exclude '/skills/' \
  "$WORK/tree/" "$DEST/"

echo "$SHA" > "$DEST/UPSTREAM"
echo "shotkit/ is now juliarvalenti/shotkit@${SHA:0:7} ($REF)"
