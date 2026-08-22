#!/usr/bin/env python3
"""Renders the mycelial network layer for docs/banner.png.

Captures a still frame of the actual mycelial canvas algorithm — byte-for-
byte the same script as the live site's animated background (see
scripts/banner-assets/mycelial-canvas.js, copied verbatim from splash.js's
canvas IIFE) — via a headless browser, at realistic hero-page proportions,
then crops and upscales a slice of it for the banner. This is deliberately
NOT re-tuned: the point is that it looks exactly like the real site's
vignette, just zoomed in on one region of it. Resize uses NEAREST so the
site's chunky pixelated cells stay crisp instead of blurring into mush.

Requires: pip install playwright pillow && playwright install chromium

Usage: gen-banner-network.py <output.png> [width] [height]
"""

import sys
from pathlib import Path

# Pillow and Playwright aren't in any lockfile: this is an asset builder run by
# hand from an env that has them (see scripts/README.md). scripts/ is type-checked
# against the standard library alone, so these are unresolvable by construction.
from PIL import Image  # ty: ignore[unresolved-import]
from playwright.sync_api import sync_playwright  # ty: ignore[unresolved-import]

# Hero viewport dimensions; matches live site's appearance.
RENDER_W, RENDER_H = 1600, 900
ZOOM = 1.4  # how much of the render to crop before upscaling to output size


def main():
    out = sys.argv[1]
    width = int(sys.argv[2]) if len(sys.argv) > 2 else 1200
    height = int(sys.argv[3]) if len(sys.argv) > 3 else 300

    harness = Path(__file__).parent / "banner-assets" / "banner-canvas.html"
    raw = Path(out).with_suffix(".raw.png")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": RENDER_W, "height": RENDER_H}, reduced_motion="reduce"
        )
        page.goto(f"file://{harness}")
        page.wait_for_timeout(300)
        page.screenshot(path=raw)
        browser.close()

    aspect = width / height
    crop_w = RENDER_W / ZOOM
    crop_h = crop_w / aspect
    left = (RENDER_W - crop_w) / 2
    top = (RENDER_H - crop_h) / 2.4  # slightly above center: more network, less empty lower half

    img = Image.open(raw)
    img = img.crop((left, top, left + crop_w, top + crop_h))
    img = img.resize((width, height), Image.NEAREST)
    img.save(out)
    raw.unlink()


if __name__ == "__main__":
    main()
