#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""
Generate the CLI Reference HTML section for docs/index.html.

Backward-compatible wrapper; the full generator is generate_docs.py (also handles markdown).

Run from repo root:
    cd mycelium-cli && uv run python ../docs/generate_cli_reference.py
"""

from __future__ import annotations

from generate_docs import main

if __name__ == "__main__":
    main()
