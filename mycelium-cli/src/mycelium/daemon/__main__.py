# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""Entry point — `python -m mycelium.daemon` runs the daemon."""

from __future__ import annotations

import sys

from mycelium.daemon.runner import main

if __name__ == "__main__":
    foreground = "--foreground" in sys.argv[1:]
    raise SystemExit(main(foreground=foreground))
