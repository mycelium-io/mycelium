#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors
"""Resolve every internal link in the docs and the repo's markdown.

`docs/*.html` is generated from the markdown under
`mycelium-cli/src/mycelium/docs/`, and the generator places the anchors. So
rewording a heading moves an `#anchor` something else still points at, and
nothing notices: the page loads and the jump does nothing.

Two kinds of target, both local: a relative path (the file must exist) and a
fragment (the target document must declare that `id` or `name`). External
`http(s)` links are skipped — checking them needs the network, and a
rate-limited GitHub is no reason to redden a docs PR.

Docs *sources* resolve as what they become. A bare `#aligner` in
`concepts/rooms.md` is a link into the generated site, not within that file, so
source links resolve against the built `docs/` tree. The built pages are then
checked one at a time, which is what catches a cross-page `#anchor` the
generator emitted without its filename.

**This warns; it does not fail** — generated anchors move as a side effect of
editing prose, so a hard gate would block PRs on something the author cannot
see. `--strict` exits non-zero, for running it deliberately.

    python3 scripts/check_docs_links.py            # report, always exits 0
    python3 scripts/check_docs_links.py --strict   # exit 1 if anything is broken
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent

# Trees to read links out of; everything else is vendored or not prose.
MARKDOWN_ROOTS = (
    Path("."),
    Path("docs"),
    Path("contracts"),
    Path("mycelium-cli/src/mycelium/docs"),
)
SKIP_DIRS = {".git", "node_modules", ".venv", "renders", ".shotkit", "dist", ".next"}

# The generated site, and the markdown tree it is generated from.
SITE_DIR = REPO_ROOT / "docs"
DOCS_SOURCE_DIR = REPO_ROOT / "mycelium-cli" / "src" / "mycelium" / "docs"

HTML_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""")
HTML_ID = re.compile(r"""\b(?:id|name)\s*=\s*["']([^"']+)["']""")
# `[text](target)` — the target stops at whitespace so a titled link
# `[t](a.md "Title")` yields just `a.md`.
MD_LINK = re.compile(r"\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)")
MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", re.MULTILINE)
# An anchor a markdown file declares by hand, e.g. `<a id="x">`.
MD_EXPLICIT_ID = re.compile(r"""<[^>]*\b(?:id|name)\s*=\s*["']([^"']+)["']""")


def slugify(heading: str) -> str:
    """GitHub's heading→anchor rule: strip formatting, lowercase, dashes."""
    text = re.sub(r"[`*_~]", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # link text only
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text.strip()).lower()


def anchors(path: Path) -> set[str]:
    """Every fragment the document at *path* can be jumped to by."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    if path.suffix in {".html", ".htm"}:
        return set(HTML_ID.findall(text))
    found = {slugify(heading) for heading in MD_HEADING.findall(text)}
    found |= set(MD_EXPLICIT_ID.findall(text))
    return found


def links_in(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix in {".html", ".htm"}:
        return HTML_HREF.findall(text)
    return [target.strip("<>") for target in MD_LINK.findall(text)]


def documents() -> list[Path]:
    """Docs pages and repo markdown, deduplicated and in a stable order."""
    found: set[Path] = set()
    for root in MARKDOWN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            # The repo root: its own markdown only, not every tree under it.
            if root == Path(".") and Path(dirpath) != base:
                dirnames[:] = []
                continue
            for name in filenames:
                if name.endswith((".md", ".html", ".htm")):
                    found.add(Path(dirpath) / name)
    return sorted(found)


def site_anchors(cache: dict[Path, set[str]]) -> set[str]:
    """Every anchor the built docs site declares, across all its pages."""
    union: set[str] = set()
    for page in sorted(SITE_DIR.glob("*.html")):
        if page not in cache:
            cache[page] = anchors(page)
        union |= cache[page]
    return union


def problems_in(path: Path, cache: dict[Path, set[str]]) -> list[str]:
    found: list[str] = []
    rel = path.relative_to(REPO_ROOT)
    # A docs source file is published into the site directory, so both its
    # relative paths and its fragments resolve there.
    published = DOCS_SOURCE_DIR in path.parents
    base = SITE_DIR if published else path.parent

    for raw in links_in(path):
        target = raw.strip()
        if not target or target.startswith(
            ("http://", "https://", "mailto:", "#!", "data:", "myc://")
        ):
            continue
        parsed = urlparse(target)
        if parsed.scheme or parsed.netloc:
            continue  # protocol-relative or a scheme we don't resolve

        fragment = unquote(parsed.fragment)
        page = unquote(parsed.path)

        if page:
            # A source link may name its neighbor in the source tree or the
            # page that neighbor becomes; either resolving is enough.
            candidates = [(base / page).resolve()]
            if published:
                candidates.append((path.parent / page).resolve())
            resolved = next((c for c in candidates if c.exists()), None)
            if resolved is None:
                found.append(f"{rel}: `{target}` → no such file")
                continue
            if resolved.is_dir():
                continue
        elif published:
            # A bare fragment from a source file lands somewhere on the site.
            if fragment and fragment not in site_anchors(cache):
                found.append(f"{rel}: `{target}` → the docs site declares no `{fragment}`")
            continue
        else:
            resolved = path  # a bare `#fragment` targets this document

        if not fragment:
            continue
        if resolved not in cache:
            cache[resolved] = anchors(resolved)
        if fragment not in cache[resolved]:
            where = "this page" if resolved == path else resolved.relative_to(REPO_ROOT)
            found.append(f"{rel}: `{target}` → {where} declares no `{fragment}`")

    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when a link is broken (default: report and exit 0)",
    )
    args = parser.parse_args()

    cache: dict[Path, set[str]] = {}
    pages = documents()
    problems = [problem for page in pages for problem in problems_in(page, cache)]

    for problem in problems:
        print(f"::warning::{problem}")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [f"## Docs links\n\n{len(pages)} document(s) checked.\n"]
        lines += (
            ["", "| Broken link |", "| --- |", *[f"| {p} |" for p in problems], ""]
            if problems
            else ["", "Every internal link and anchor resolves.", ""]
        )
        with Path(summary).open("a") as handle:
            handle.write("\n".join(lines) + "\n")

    if problems:
        print(f"\n{len(problems)} broken internal link(s) across {len(pages)} document(s).")
        return 1 if args.strict else 0

    print(f"{len(pages)} document(s): every internal link and anchor resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
