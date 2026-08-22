#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Open a pull request for whatever the screenshot capture just rewrote, in one
# repository. Both sinks the pipeline writes to — docs/ here, the PNGs at the
# root of the splash repo — are published the same way, so this takes the
# checkout and the paths to look at:
#
#   scripts/publish-screenshots.sh <repo-dir> <pathspec> <label>
#
# Needs GH_TOKEN in the environment, with push and pull-request rights on that
# checkout's remote. A no-op (exit 0) when the capture reproduced the committed
# assets byte for byte, which is the expected result on a UI that hasn't moved.
set -euo pipefail

repo_dir=$1
pathspec=$2
label=$3

cd "$repo_dir"

if [ -z "$(git status --porcelain -- "$pathspec")" ]; then
  echo "::notice::$label: screenshots already match the running UI — nothing to publish."
  exit 0
fi

base=$(git rev-parse --abbrev-ref HEAD)
branch="screenshots/run-${GITHUB_RUN_ID}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git checkout -b "$branch"
git add -- "$pathspec"
git commit -m "Refresh app screenshots from the running UI"

# Retry the push: a transient network failure on a manual, idempotent workflow
# should not cost a re-run of the whole capture.
for delay in 2 4 8 0; do
  if git push -u origin "$branch"; then
    break
  fi
  if [ "$delay" = 0 ]; then
    echo "::error::$label: could not push $branch"
    exit 1
  fi
  sleep "$delay"
done

gh pr create \
  --base "$base" \
  --head "$branch" \
  --title "Refresh app screenshots" \
  --body "$(
    cat <<EOF
Captured from the frontend in mock mode by the \`Screenshots\` workflow
([run](${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID})),
which regenerates $label's committed assets the same way \`pnpm screenshots\`
does locally.

Worth an eye on the rendered diff before merging: a runner and a laptop do not
rasterize identically, so a small visual delta here is expected and a large one
means the UI actually changed.
EOF
  )"
