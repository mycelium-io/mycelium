#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# A sandbox: this worktree's whole product in one container, beside whatever
# runs on the machine, to try a change the way someone would use it.
#
#   sandbox/sandbox.sh start     build from this worktree and start it
#   sandbox/sandbox.sh creds     give its Claude Code this machine's sign-in again
#   sandbox/sandbox.sh exec ...  run a command inside (a shell with none)
#   sandbox/sandbox.sh url       where its UI is
#   sandbox/sandbox.sh logs      the supervisor's output
#   sandbox/sandbox.sh stop      stop it and remove it and its image
#
# One per worktree, named after the worktree's folder. Only the UI is
# published, on a free port on 127.0.0.1.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
name="$(basename "$root" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_.-\n' '-')"
container="mycelium-sandbox-$name"
image="mycelium-sandbox:$name"

die() { echo "sandbox: $*" >&2; exit 1; }

# The versions the desktop app ships, read from where it pins them.
pin() {
  sed -n "s/^$1=\"\(.*\)\"$/\1/p" "$root/mycelium-desktop/scripts/stage-sidecars.sh"
}

url() {
  local port
  port="$(docker port "$container" 8080/tcp 2>/dev/null | head -n 1 | sed 's/.*://')"
  [ -n "$port" ] || die "$container isn't running; start it with: sandbox/sandbox.sh start"
  echo "http://localhost:$port"
}

# Claude Code's sign-in on this machine, handed to the container on stdin, so
# it's never in the image, an environment variable or a file here. Only the
# access token goes in: the container never refreshes it, so it can't rotate
# the refresh token out from under this machine's own Claude Code. When it
# expires, run `creds` again.
creds() {
  local raw
  if [ "$(uname)" = Darwin ]; then
    raw="$(security find-generic-password -s "Claude Code-credentials" -w)" \
      || die "no Claude Code sign-in in this Mac's Keychain; sign in to Claude Code first"
  elif [ -f "$HOME/.claude/.credentials.json" ]; then
    raw="$(cat "$HOME/.claude/.credentials.json")"
  else
    die "no Claude Code sign-in here; sign in to Claude Code first"
  fi
  printf '%s' "$raw" | docker exec -i "$container" python3 -c '
import json, os, sys
creds = json.load(sys.stdin)
creds.get("claudeAiOauth", {}).pop("refreshToken", None)
path = os.path.expanduser("~/.claude/.credentials.json")
os.makedirs(os.path.dirname(path), exist_ok=True)
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(creds, f)
'
  echo "Claude Code in $container is signed in as this machine's Claude Code."
}

#: Free space a build needs, in GB. An image is a few GB, and a full disk
#: leaves Docker's storage failing every write until Docker restarts.
MIN_FREE_GB=15

start() {
  docker info >/dev/null 2>&1 || die "Docker isn't running"
  local free_gb
  free_gb=$(( $(df -Pk "$root" | awk 'NR==2 {print $4}') / 1024 / 1024 ))
  if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    die "only ${free_gb} GB free here; a build needs ${MIN_FREE_GB}. Free some space first"
  fi
  docker build \
    --file "$root/sandbox/Dockerfile" \
    --build-arg HERDR_TAG="$(pin HERDR_TAG)" \
    --build-arg SLIMCTL_TAG="$(pin SLIMCTL_TAG)" \
    --build-arg NODE_VERSION="$(pin NODE_VERSION)" \
    --build-arg PI_VERSION="$(pin PI_VERSION)" \
    --build-arg EMBEDDING_MODEL="$(pin EMBEDDING_MODEL)" \
    --label "mycelium.sandbox=$name" \
    --tag "$image" "$root"
  # The image this one replaced, left untagged by the build.
  docker image prune --force --filter "label=mycelium.sandbox=$name" >/dev/null
  docker rm -f "$container" >/dev/null 2>&1 || true
  docker run --detach --name "$container" --init=false \
    --publish 127.0.0.1::8080 "$image" >/dev/null
  creds
  echo "Started $container from $root."
  echo "UI:    $(url)"
  echo "Shell: sandbox/sandbox.sh exec"
}

case "${1:-}" in
  start) start ;;
  creds) creds ;;
  exec)
    shift
    if [ $# -eq 0 ]; then set -- bash; fi
    flags=(-i)
    if [ -t 0 ]; then flags=(-it); fi
    docker exec "${flags[@]}" -w /work "$container" "$@"
    ;;
  url) url ;;
  logs) docker logs "${@:2}" "$container" ;;
  stop)
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker rmi "$image" >/dev/null 2>&1 || true
    echo "Stopped $container and removed its image."
    ;;
  *) sed -n '5,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
