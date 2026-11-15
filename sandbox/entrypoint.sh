#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Inside the sandbox: everything listens on 127.0.0.1 as on a person's
# machine, so the UI alone is forwarded to the port Docker publishes. The hub,
# SLIM and herdr stay inside; they're driven with `sandbox.sh exec`.
set -euo pipefail

socat TCP-LISTEN:8080,fork,reuseaddr TCP:127.0.0.1:3717 &

# A Claude Code token of the sandbox's own (`claude setup-token`), mounted
# read-only by sandbox.sh: read here, so it's in the processes' environment
# and not in the container's configuration.
if [ -r /run/secrets/claude-token ]; then
  CLAUDE_CODE_OAUTH_TOKEN="$(cat /run/secrets/claude-token)"
  export CLAUDE_CODE_OAUTH_TOKEN
fi

exec mycelium desktop serve --root /work
