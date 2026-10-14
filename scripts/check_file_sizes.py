#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
"""Keep big files out of git, and committed PNGs compressed.

Two checks, because a file committed to git is in every clone forever: a
replaced screenshot still costs its old bytes in the history.

  1. No tracked file is over LIMIT_BYTES, unless ALLOWED names it with a
     reason. Sizes are git's own (the blob in the index), so a file stored in
     Git LFS counts as its pointer, a few hundred bytes. That is how videos go
     in (`.gitattributes`); images stay in git, compressed. An ALLOWED entry
     whose file is gone or back under the limit is stale, and fails too.
  2. With --pngs-since or --all-pngs: no PNG that oxipng could losslessly
     shrink by more than MAX_SAVING. `pnpm screenshots`, `gen-og.sh` and
     `gen-banner.sh` optimize what they write; for any other image,
     `npm run optimize-png -- <file>` in mycelium-frontend/ does the same.

The size check is stdlib. The PNG check needs oxipng's Python bindings:

    python3 scripts/check_file_sizes.py
    uv run --no-project --with pyoxipng==9.1.1 python scripts/check_file_sizes.py --pngs-since origin/main
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

LIMIT_BYTES = 400 * 1024

# Tracked files allowed over the limit, each with the reason it can't be
# smaller. Keep it short: the answer for a new big file is usually to
# compress it, or to put it in LFS if it's a video.
ALLOWED: dict[str, str] = {
    "docs/logo.png": "the 2048px logo master, already optimized; smaller only by resizing it",
    "mycelium-frontend/public/logo.png": "a copy of the 2048px logo master the app serves",
    "mycelium-frontend/src/app/icon.png": "a copy of the 2048px logo master Next makes the favicons from",
    "docs/og.png": "the 1200x630 social card, a full-bleed gradient, already optimized",
    "mycelium-desktop/src-tauri/icons/icon.icns": "the macOS icon bundle `tauri icon` writes, every size up to 1024px",
    "mycelium-frontend/package-lock.json": "npm's lockfile, which has to be committed",
}

# A PNG oxipng (at level 2, its fast setting) shrinks by more than this was
# committed without the optimizer.
MAX_SAVING = 0.10


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout


def tracked_sizes() -> dict[str, int]:
    """Every tracked path and the size of its blob in the index."""
    entries = [line.split("\t", 1) for line in git("ls-files", "-s", "-z").split("\0") if line]
    paths = {meta.split()[1]: path for meta, path in entries if not meta.startswith("160000")}
    batch = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objectsize)"],
        cwd=REPO_ROOT,
        input="\n".join(paths),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    sizes: dict[str, int] = {}
    for line in batch.splitlines():
        sha, size = line.split()
        sizes[paths[sha]] = int(size)
    # Two paths with the same content share a blob; give each its size.
    for meta, path in entries:
        sha = meta.split()[1]
        if sha in paths and path not in sizes:
            sizes[path] = sizes[paths[sha]]
    return sizes


def fix_for(path: str) -> str:
    """What usually makes a file this big fit."""
    if path.lower().endswith(".png"):
        return f"Compress it (`npm run optimize-png -- ../{path}` in mycelium-frontend/), or make it smaller"
    if path.lower().endswith((".mp4", ".webm", ".mov")):
        return "Put it in Git LFS (a pattern in .gitattributes, then commit it again)"
    return "Make it smaller"


def size_problems(sizes: dict[str, int]) -> list[str]:
    found = [
        f"{path}: {size // 1024} KiB, over the {LIMIT_BYTES // 1024} KiB limit. {fix_for(path)}, or add it "
        f"to ALLOWED in scripts/check_file_sizes.py with the reason it can't be smaller"
        for path, size in sorted(sizes.items())
        if size > LIMIT_BYTES and path not in ALLOWED
    ]
    for path in sorted(ALLOWED):
        if path not in sizes:
            found.append(
                f"scripts/check_file_sizes.py: ALLOWED names {path}, which isn't tracked; remove it"
            )
        elif sizes[path] <= LIMIT_BYTES:
            found.append(
                f"scripts/check_file_sizes.py: ALLOWED names {path}, which is under the limit now "
                f"({sizes[path] // 1024} KiB); remove it",
            )
    return found


def optimized(path: str) -> tuple[str, int, int]:
    """A PNG's path, its size, and its size after a lossless oxipng pass."""
    # Installed only for this check (`--with pyoxipng`), so not where ty looks.
    import oxipng  # noqa: PLC0415  # ty: ignore[unresolved-import]

    data = (REPO_ROOT / path).read_bytes()
    out = oxipng.optimize_from_memory(data, level=2, strip=oxipng.StripChunks.safe())
    return path, len(data), len(out)


def png_problems(paths: list[str]) -> list[str]:
    if not paths:
        return []
    if importlib.util.find_spec("oxipng") is None:
        return [
            "the PNG check needs oxipng: run it under `uv run --no-project --with pyoxipng==9.1.1 python ...`"
        ]
    # The bindings hold the GIL, so a process per core rather than threads.
    with ProcessPoolExecutor() as pool:
        results = list(pool.map(optimized, paths))
    found = []
    for path, before, after in results:
        saving = 1 - after / before
        if saving > MAX_SAVING:
            found.append(
                f"{path}: oxipng shrinks it {saving:.0%} with no change to the pixels "
                f"({before // 1024} -> {after // 1024} KiB). Run `npm run optimize-png -- ../{path}` "
                f"in mycelium-frontend/ and commit the result",
            )
    return found


def changed_pngs(since: str) -> list[str]:
    """PNGs added or changed since a commit, present in the working tree."""
    names = git(
        "diff", "--name-only", "--diff-filter=AMR", "-z", since, "--", "*.png", "*.PNG"
    ).split("\0")
    return sorted(name for name in names if name and (REPO_ROOT / name).is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    pngs = parser.add_mutually_exclusive_group()
    pngs.add_argument(
        "--pngs-since", metavar="REF", help="also check PNGs added or changed since REF"
    )
    pngs.add_argument("--all-pngs", action="store_true", help="also check every tracked PNG")
    args = parser.parse_args()

    sizes = tracked_sizes()
    problems = size_problems(sizes)
    checked_pngs: list[str] = []
    if args.all_pngs:
        checked_pngs = sorted(p for p in sizes if p.lower().endswith(".png"))
    elif args.pngs_since:
        checked_pngs = changed_pngs(args.pngs_since)
    problems += png_problems(checked_pngs)

    for problem in problems:
        # `::error` renders as an annotation under Actions, plain text locally.
        print(f"::error::{problem}")
    if problems:
        print(f"\n{len(problems)} file size problem(s).")
        return 1

    print(
        f"{len(sizes)} tracked file(s) within {LIMIT_BYTES // 1024} KiB ({len(ALLOWED)} allowed over it); "
        f"{len(checked_pngs)} PNG(s) checked, all compressed.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
