#!/usr/bin/env python3
"""
Generate the CLI Reference HTML section for docs/index.html.

This is a backward-compatible wrapper — the full generator is now
generate_docs.py which also handles markdown content sections.

Run from repo root:
    cd mycelium-cli && uv run python ../docs/generate_cli_reference.py
"""

from __future__ import annotations

from generate_docs import main

if __name__ == "__main__":
    main()
