// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The docs' glass droplets, as a backdrop.
 *
 * The docs site draws droplets of iridescent glass behind the page in WebGL:
 * drops drifting up, reaching for each other with hyphae that carry pulses,
 * now and then pooling into one. `--backdrop glass` puts that scene behind a
 * capture instead of a gradient.
 *
 * As with `canvas`, the algorithm is the project's, named in
 * `shotkit.config.json` (`backdrop.glass`; in mycelium, `docs/glass.js`, the
 * file the docs load), and read rather than copied. The script exposes one seam
 * for a recorder: with `window.__glassManual` set before it runs, it skips its
 * own animation loop and `window.__glass.seek(frame)` steps the scene to a
 * frame of a 30fps clock and draws it.
 *
 * Two uses. A still (a card, a staged screenshot) gets one frame, rendered to a
 * PNG once per theme and size and cached. A staged video gets the scene live
 * on the stage page and seeks it once per beat, so the drops move across the
 * take; `Math.random` is seeded on every page, so the several pages a take is
 * staged on all hold the same scene at the same frame.
 */

import { readFile, stat } from "node:fs/promises";
import { CONFIG_FILE, GLASS_PATH } from "./project.mjs";

/** The project's glass script, or null when its config names none. */
export const GLASS_SOURCE = GLASS_PATH;

/** Any constant; one seed is one scene, so a committed asset does not churn. */
export const DEFAULT_SEED = 1129;

/** The scene's clock: the script steps at 30fps whatever the take's fps. */
export const GLASS_FPS = 30;

/**
 * A staged video re-draws the scene every other step: the drops drift too
 * slowly for 15 draws a second to show, and a draw is most of a frame's cost.
 */
export const GLASS_VIDEO_STEP = 2;

/** The resolution a staged video draws the scene at; it is a soft background. */
export const GLASS_VIDEO_SCALE = 0.5;

/** @type {Map<string, Promise<string>>} */
const cache = new Map();

export async function glassSource() {
  if (!GLASS_SOURCE) {
    throw new Error(
      `the glass backdrop needs the docs' glass script, and ${CONFIG_FILE} names none (backdrop.glass). ` +
        "Use --backdrop mycelium for the gradient instead.",
    );
  }
  try {
    const [script, info] = await Promise.all([readFile(GLASS_SOURCE, "utf8"), stat(GLASS_SOURCE)]);
    return { script, version: info.mtimeMs };
  } catch (e) {
    throw new Error(`the glass backdrop needs ${GLASS_SOURCE} (${e.code ?? e.message}).`);
  }
}

/** mulberry32 in place of `Math.random`, so one seed is one scene. */
function seedJs(seed) {
  return `(function(){var s=${seed >>> 0};Math.random=function(){s=s+0x6D2B79F5|0;` +
    `var t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;` +
    `return((t^t>>>14)>>>0)/4294967296};})();`;
}

/**
 * The scene as markup to drop into a page that fills the viewport: a canvas
 * behind everything, and the script under manual time. The script sizes its
 * canvas to the window, so the page's viewport is the scene's size.
 * `scale` draws it at a fraction of the page's resolution and upscales it: a
 * video re-draws the scene every frame, and a software GL can't afford 1x.
 * @param {string} script @param {{theme?:"dark"|"light", seed?:number, scale?:number}} [opts]
 */
export function glassMarkup(script, opts = {}) {
  const dark = opts.theme !== "light";
  const inline = script.replace(/<\/script/gi, "<\\/script");
  return `<canvas id="mycelium-bg" style="position:absolute;inset:0;width:100%;height:100%;display:block"></canvas>` +
    `<script>${seedJs(opts.seed ?? DEFAULT_SEED)}window.__glassManual=true;window.__glassScale=${opts.scale ?? 1};` +
    `document.documentElement.classList.${dark ? "add" : "remove"}("dark");</script>` +
    `<script>${inline}</script>`;
}

/**
 * One frame of the scene as a CSS background, for a still.
 * @param {import("./engine.mjs").Engine} eng
 * @param {{theme?:"dark"|"light", seed?:number, width?:number, height?:number, frame?:number}} [opts]
 * @returns {Promise<string>}
 */
export async function glassArt(eng, opts = {}) {
  const theme = opts.theme === "light" ? "light" : "dark";
  const width = opts.width ?? 1920;
  const height = opts.height ?? 1080;
  const { script, version } = await glassSource();
  const key = `${theme}:${opts.seed ?? DEFAULT_SEED}:${width}x${height}:${opts.frame ?? 0}:${version}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const pending = (async () => {
    const html = `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%;overflow:hidden}` +
      `#wrap{position:relative;width:${width}px;height:${height}px}</style></head><body><div id="wrap">` +
      `${glassMarkup(script, { theme, seed: opts.seed })}</div>` +
      `<script>window.__glass&&window.__glass.seek(${opts.frame ?? 0})</script></body></html>`;
    const buf = await eng.captureStatic({ html, selector: "#wrap", theme, scale: 1, width, height });
    return `url("data:image/png;base64,${buf.toString("base64")}") center/cover no-repeat`;
  })();
  pending.catch(() => cache.delete(key));
  cache.set(key, pending);
  return pending;
}
