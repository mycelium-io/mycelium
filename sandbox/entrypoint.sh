#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
#
# Inside the sandbox: everything listens on 127.0.0.1 as on a person's
# machine, so the UI alone is forwarded to the port Docker publishes. The hub,
# SLIM and herdr stay inside; they're driven with `sandbox.sh exec`.
set -euo pipefail

socat TCP-LISTEN:8080,fork,reuseaddr TCP:127.0.0.1:3717 &

exec mycelium desktop serve --root /work
