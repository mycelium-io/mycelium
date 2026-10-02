// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A project's own background canvas, as something a card can sit on.
 *
 * A docs site often paints something behind its pages: mycelium's paints a
 * hypha network (and now glass droplets). A framed screenshot wants the same
 * thing behind the window, a desktop rather than a gradient, so this runs the
 * project's canvas script once and hands back a CSS background the card, sheet
 * and stage renderers drop into their backdrop layer. That is `--backdrop canvas`.
 *
 * The script is not reimplemented here. The project names it in
 * `shotkit.config.json` (`backdrop.canvas`) and this reads that file rather than
 * carrying a copy to keep in step. The contract is small: an IIFE that draws
 * into `<canvas id="mycelium-bg">`, may read the `dark`/`light` class on
 * `<html>` and the `--canvas-bg`, `--canvas-ink` and `--canvas-alpha` custom
 * properties, and paints a still frame under prefers-reduced-motion (which
 * every shotkit context sets), so there is nothing to wait for. A project that
 * names no script has no `canvas` backdrop; the gradient presets don't need it.
 *
 * The render is cached per theme and seed for the life of the process, so the
 * daemon paints it on the first framed shot and every later one reuses it. A
 * run of shots therefore shares one desktop instead of each inventing its own.
 */

import { readFile, stat } from "node:fs/promises";
import { CANVAS_PATH, CANVAS_PIXELATED, CANVAS_SIZE, CONFIG_FILE } from "./project.mjs";

/** The project's canvas script, or null when its config names none. */
export const CANVAS_SOURCE = CANVAS_PATH;

/**
 * How the art layer is upscaled to the backdrop. Smooth by default; a project
 * whose canvas is pixel art (one image pixel per cell, as mycelium's hypha
 * network is) sets `backdrop.pixelated` so the cells stay hard-edged.
 */
export const ART_RENDERING = CANVAS_PIXELATED ? "pixelated" : "auto";

/**
 * The `--canvas-*` values handed to the script, from the mycelium docs site
 * (docs/mycelium.css), whose network was the first script this ran. Dark ink on
 * a light ground reads heavier at equal alpha, so light runs quieter.
 */
export const CANVAS_VARS = {
  dark: { bg: "#0c0e11", rgb: "12, 14, 17", ink: "92, 199, 210", alpha: 1 },
  light: { bg: "#f4ecda", rgb: "244, 236, 218", ink: "12, 125, 143", alpha: 0.72 },
};

/**
 * How hard the vignette veils the canvas, per theme: center, midpoint, edge.
 *
 * Light is veiled less than dark, not more: light already runs at a lower
 * `--canvas-alpha`, so an equal veil quiets it twice.
 */
export const VEIL = {
  dark: [0.3, 0.58, 0.9],
  light: [0.12, 0.32, 0.68],
};

/**
 * A vignette over the canvas, in the ground's own color.
 *
 * A site can run its background at full strength because prose sits on
 * near-solid paper above it. A screenshot has no such pane: the canvas is next
 * to the window rather than under it, and at full strength the corners pull the
 * eye off the thing being shown. So it is veiled a little everywhere and a lot
 * at the edges.
 *
 * @param {"dark"|"light"} theme
 */
function vignette(theme) {
  const g = CANVAS_VARS[theme].rgb;
  const [center, mid, edge] = VEIL[theme];
  return (
    `radial-gradient(125% 125% at 50% 40%, rgba(${g},${center}) 0%, ` +
    `rgba(${g},${mid}) 45%, rgba(${g},${edge}) 100%)`
  );
}

/**
 * Any constant would do; the point is that it is one. A random scene per shot
 * would only mean a docs asset whose diff is noise. `--backdrop-seed` picks a
 * different one.
 */
export const DEFAULT_SEED = 4271;

/** @type {Map<string, Promise<string>>} */
const cache = new Map();

/** The canvas script, and when it last changed. */
export async function canvasSource() {
  const path = CANVAS_SOURCE;
  if (!path) {
    throw new Error(
      `--backdrop canvas needs a canvas script, and ${CONFIG_FILE} names none (backdrop.canvas). ` +
        "Use --backdrop mycelium for the gradient instead.",
    );
  }
  try {
    const [script, info] = await Promise.all([readFile(path, "utf8"), stat(path)]);
    return { script, version: info.mtimeMs };
  } catch (e) {
    throw new Error(
      `--backdrop canvas could not read the canvas script at ${path} (${e.code ?? e.message}). ` +
        "Use --backdrop mycelium for the gradient instead.",
    );
  }
}

/**
 * Replace `Math.random` before the script runs, so one seed paints one scene.
 * mulberry32: short, and good enough for artwork.
 * @param {number} seed
 */
function seedScript(seed) {
  return `<script>(function(){var s=${seed >>> 0};Math.random=function(){s=s+0x6D2B79F5|0;` +
    `var t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;` +
    `return((t^t>>>14)>>>0)/4294967296};})();</script>`;
}

/**
 * A standalone page that runs the script and stops.
 *
 * The canvas is shot at its natural size and the upscaling happens later, in
 * the backdrop, where the final size is known.
 *
 * @param {string} script the canvas script
 * @param {{theme?:"dark"|"light", seed?:number}} [opts]
 */
export function canvasDocument(script, opts = {}) {
  const theme = opts.theme === "light" ? "light" : "dark";
  const v = CANVAS_VARS[theme];
  // `</script>` inside the script would end the block early.
  const inline = script.replace(/<\/script/gi, "<\\/script");
  return `<!doctype html><html class="${theme}"><head><meta charset="utf-8"><style>
html,body{margin:0;padding:0;background:${v.bg}}
html{--canvas-bg:${v.bg};--canvas-ink:${v.ink};--canvas-alpha:${v.alpha}}
canvas{display:block;image-rendering:${ART_RENDERING}}
</style></head><body>${seedScript(opts.seed ?? DEFAULT_SEED)}<canvas id="mycelium-bg"></canvas><script>${inline}</script></body></html>`;
}

/**
 * The canvas as a CSS background value, painted on first use and cached after.
 *
 * `cover` rather than a fixed size: a card's width is whatever its content
 * shrink-wraps to, and a fixed size would leave bands of flat ground beside a
 * wide one.
 *
 * @param {import("./engine.mjs").Engine} eng
 * @param {{theme?:"dark"|"light", seed?:number}} [opts]
 * @returns {Promise<string>}
 */
export async function canvasArt(eng, opts = {}) {
  const theme = opts.theme === "light" ? "light" : "dark";
  const seed = opts.seed ?? DEFAULT_SEED;
  // The script lives outside src/, so editing it does not restart the daemon
  // the way editing shotkit does. Keying on its mtime is what stops a long-lived
  // daemon from serving a scene painted by a version of it that is gone.
  const { script, version } = await canvasSource();
  const key = `${theme}:${seed}:${version}`;
  const hit = cache.get(key);
  if (hit) return hit;

  const pending = (async () => {
    const buf = await eng.captureStatic({
      html: canvasDocument(script, { theme, seed }),
      selector: "#mycelium-bg",
      theme,
      scale: 1,
      ...CANVAS_SIZE,
    });
    // One value, two background layers: CSS paints the first over the second, so
    // the vignette rides on the canvas without a second element to position.
    return `${vignette(theme)}, url("data:image/png;base64,${buf.toString("base64")}") center/cover no-repeat`;
  })();
  // A failed render must not become the cached answer for the rest of the
  // process — the next shot should get another go at it.
  pending.catch(() => cache.delete(key));
  cache.set(key, pending);
  return pending;
}
