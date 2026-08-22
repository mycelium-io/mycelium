// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The mycelial network, as something a card can sit on.
 *
 * The docs site paints a growing hypha network behind the page, and
 * `docs/banner.png` is a still frame of that same canvas, cropped and upscaled.
 * A framed app screenshot wants the same thing behind the window — a desktop,
 * not a gradient — so this renders the network once and hands back a CSS
 * background the card renderer can drop into its backdrop layer.
 *
 * The algorithm is not reimplemented here. `scripts/banner-assets/mycelial-canvas.js`
 * is already the repo's shared copy of the live site's canvas IIFE, kept there
 * so the banner looks like the site; this reads that file rather than adding a
 * third copy to keep in step.
 *
 * Two things make it cheap enough to put on every shot. The render is one small
 * PNG — one image pixel per cell, a couple of hundred pixels across, upscaled
 * with `image-rendering: pixelated`, which is where the chunky cells come from
 * — and it is cached per theme for the life of the process, so the daemon grows
 * a network on the first framed shot and every later one reuses it. A run of
 * shots therefore shares one desktop instead of each inventing its own.
 */

import { readFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { REPO_ROOT } from "./engine.mjs";

/** The shared canvas algorithm, relative to the repo root. */
export const CANVAS_SOURCE = "scripts/banner-assets/mycelial-canvas.js";

/**
 * The docs site's `--canvas-*` values (docs/mycelium.css), which is what makes
 * this the site's network rather than a lookalike. Dark ink on a light ground
 * reads heavier at equal alpha, so light runs quieter — that asymmetry is the
 * site's, kept rather than re-tuned.
 */
export const CANVAS_VARS = {
  dark: { bg: "#0c0e11", ink: "92, 199, 210", alpha: 1 },
  light: { bg: "#f4ecda", ink: "12, 125, 143", alpha: 0.72 },
};

/**
 * Hero-page proportions, the same ones `gen-banner-network.py` renders at. The
 * colony count in the algorithm is fixed, so the render size *is* the density:
 * grow the network on a larger page and it thins out. Matching the banner keeps
 * it looking like the site.
 */
const RENDER_W = 1600;
const RENDER_H = 900;

/**
 * Any constant would do; the point is that it is one. Every network the
 * algorithm grows is plausible, so a random one per shot would only mean a docs
 * asset whose diff is noise. `--backdrop-seed` picks a different one.
 */
export const DEFAULT_SEED = 4271;

/** @type {Map<string, Promise<string>>} */
const cache = new Map();

/** The canvas IIFE, and when it last changed. */
export async function canvasSource() {
  const path = resolve(REPO_ROOT, CANVAS_SOURCE);
  try {
    const [script, info] = await Promise.all([readFile(path, "utf8"), stat(path)]);
    return { script, version: info.mtimeMs };
  } catch (e) {
    throw new Error(
      `the mycelial backdrop needs the shared canvas algorithm at ${path} (${e.code ?? e.message}). ` +
        "Use --backdrop mycelium for the gradient instead.",
    );
  }
}

/**
 * Replace `Math.random` before the algorithm runs, so one seed grows one
 * network. mulberry32: short, and good enough for artwork.
 * @param {number} seed
 */
function seedScript(seed) {
  return `<script>(function(){var s=${seed >>> 0};Math.random=function(){s=s+0x6D2B79F5|0;` +
    `var t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;` +
    `return((t^t>>>14)>>>0)/4294967296};})();</script>`;
}

/**
 * A standalone page that grows the network and stops.
 *
 * The canvas is left at its natural size — one CSS pixel per cell — so the
 * capture is the raw cell grid and the upscaling happens later, in the card,
 * where the final size is known. Under reduced motion (which every shotkit
 * context sets) the algorithm paints its grown network once instead of
 * animating, so there is nothing to wait for.
 *
 * @param {string} script the canvas algorithm
 * @param {{theme?:"dark"|"light", seed?:number}} [opts]
 */
export function networkDocument(script, opts = {}) {
  const theme = opts.theme === "light" ? "light" : "dark";
  const v = CANVAS_VARS[theme];
  // `</script>` cannot appear in the algorithm today; inlining it is still the
  // one place where that would end the block early.
  const inline = script.replace(/<\/script/gi, "<\\/script");
  return `<!doctype html><html class="${theme}"><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:${v.bg}}
html{--canvas-bg:${v.bg};--canvas-ink:${v.ink};--canvas-alpha:${v.alpha}}
canvas{display:block;image-rendering:pixelated}
</style></head><body>${seedScript(opts.seed ?? DEFAULT_SEED)}<canvas id="mycelium-bg"></canvas><script>${inline}</script></body></html>`;
}

/**
 * The network as a CSS background value, grown on first use and cached after.
 *
 * `cover` rather than a fixed cell size: a card's width is whatever its content
 * shrink-wraps to, and a fixed size would leave bands of flat ground beside a
 * wide one. The cells scale with the card the way the banner's do.
 *
 * @param {import("./engine.mjs").Engine} eng
 * @param {{theme?:"dark"|"light", seed?:number}} [opts]
 * @returns {Promise<string>}
 */
export async function mycelialArt(eng, opts = {}) {
  const theme = opts.theme === "light" ? "light" : "dark";
  const seed = opts.seed ?? DEFAULT_SEED;
  // The algorithm lives outside src/, so editing it does not restart the daemon
  // the way editing shotkit does. Keying on its mtime is what stops a long-lived
  // daemon from serving a network grown by a version of it that is gone.
  const { script, version } = await canvasSource();
  const key = `${theme}:${seed}:${version}`;
  const hit = cache.get(key);
  if (hit) return hit;

  const pending = (async () => {
    const buf = await eng.captureStatic({
      html: networkDocument(script, { theme, seed }),
      selector: "#mycelium-bg",
      theme,
      scale: 1,
      width: RENDER_W,
      height: RENDER_H,
    });
    return `url("data:image/png;base64,${buf.toString("base64")}") center/cover no-repeat`;
  })();
  // A failed render must not become the cached answer for the rest of the
  // process — the next shot should get another go at it.
  pending.catch(() => cache.delete(key));
  cache.set(key, pending);
  return pending;
}
