// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The tech-demo stage: a capture tilted in perspective, floating over a dark
 * ground with a glow behind it — the angled product shot on a launch page.
 *
 * It is a re-render, like `--chrome`: the capture goes in as an image and the
 * browser does the 3D, so the type stays sharp under the transform instead of
 * being resampled by an image library. Stills pass through once; a video passes
 * each of its frames through the same page (see `restage` in video.mjs), which
 * is also what lets the angle drift across a take.
 *
 * The angle is three rotations, applied in this order: X tips the top away from
 * the viewer, Y turns the window to face left or right, and Z is the dutch tilt.
 */

import { backdrop, palette } from "./theme.mjs";

/** Degrees: [x, y, z]. Positive x tips the top away; positive y turns the window to face right. */
export const TILT_PRESETS = {
  hero: [16, -20, 5],
  left: [10, 26, -4],
  right: [10, -26, 4],
  dutch: [0, 0, -7],
  desk: [42, 0, -22],
  flat: [0, 0, 0],
};

export const STAGE_DEFAULTS = {
  width: 1920,
  height: 1080,
  perspective: 1800,
  fit: 0.74,
  backdrop: "stage",
};

/** The default ground: near-black, a little lift where the glow sits. */
const STAGE_GROUND = {
  dark: "radial-gradient(90% 80% at 50% 45%, #141a24 0%, #0b0e13 55%, #050608 100%)",
  light: "radial-gradient(90% 80% at 50% 45%, #ffffff 0%, #eef1f5 55%, #dde2e9 100%)",
};

/** Whether a spec asks for the stage: `--demo`, or any `--tilt`. */
export function isStaged(spec) {
  return Boolean(spec.demo) || (spec.tilt !== undefined && spec.tilt !== false);
}

/** Read `--stage 1920x1080`. */
export function parseStageSize(value) {
  if (!value) return {};
  const m = /^(\d+)x(\d+)$/.exec(String(value).trim());
  if (!m) throw new Error(`--stage takes WxH in CSS pixels, like 1920x1080, not "${value}"`);
  return { width: Number(m[1]), height: Number(m[2]) };
}

/**
 * The stage's options out of a spec. `--backdrop` keeps meaning what it means
 * everywhere else; left unset, the stage brings its own darker ground.
 * @param {Record<string, any>} spec
 */
export function pickStage(spec) {
  return {
    tilt: parseTilt(spec.tilt),
    ...parseStageSize(spec.stage),
    ...(spec.perspective ? { perspective: spec.perspective } : {}),
    ...(spec.fit ? { fit: spec.fit } : {}),
    ...(spec.backdrop ? { backdrop: spec.backdrop } : {}),
    ...(spec.radius !== undefined ? { radius: spec.radius } : {}),
    glow: spec.glow !== false,
    reflect: Boolean(spec.reflect),
    grid: Boolean(spec.grid),
  };
}

/**
 * Read `--tilt`: a preset name, or `x,y,z` in degrees (`z` alone tilts dutch).
 * @param {string|boolean|undefined} value
 * @returns {[number, number, number]}
 */
export function parseTilt(value) {
  if (value === undefined || value === true || value === "") return TILT_PRESETS.hero;
  const text = String(value).trim();
  if (TILT_PRESETS[text]) return TILT_PRESETS[text];
  const parts = text.split(",").map((s) => Number(s.trim()));
  if (parts.some((n) => !Number.isFinite(n)) || parts.length > 3) {
    throw new Error(
      `--tilt takes a preset (${Object.keys(TILT_PRESETS).join(", ")}) or x,y,z in degrees, not "${text}"`,
    );
  }
  if (parts.length === 1) return [0, 0, parts[0]];
  return [parts[0], parts[1], parts[2] ?? 0];
}

/**
 * The rotations as a CSS transform, with the perspective riding in it, so the
 * window projects on its own and needs no 3D context from a parent.
 */
export function tiltTransform([x, y, z], scale = 1, perspective = STAGE_DEFAULTS.perspective) {
  const r = (n) => Math.round(n * 1000) / 1000;
  return `perspective(${r(perspective)}px) scale(${r(scale)}) ` +
    `rotateX(${r(x)}deg) rotateY(${r(y)}deg) rotateZ(${r(z)}deg)`;
}

/**
 * The tilt at `t` in [0, 1] of a take: the angle swung by `drift` degrees on y
 * and a third of it on x, centered on the configured angle, with a slow push in.
 * An eased sweep, so the take opens and closes on a held angle.
 * @param {[number, number, number]} tilt @param {number} drift @param {number} t
 */
export function driftAt(tilt, drift, t) {
  const e = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
  const s = e - 0.5;
  return {
    tilt: /** @type {[number, number, number]} */ ([tilt[0] - (drift / 3) * s, tilt[1] + drift * s, tilt[2]]),
    zoom: 1 + (drift ? 0.05 * e : 0),
  };
}

/**
 * @typedef {object} StageOptions
 * @property {number} imgWidth the image's width in CSS pixels
 * @property {number} imgHeight
 * @property {[number, number, number]} tilt
 * @property {"window"|"none"} [frame] `window` rounds and borders a raw page
 *   capture; `none` stages an image that already carries its own frame
 * @property {"dark"|"light"} [theme]
 * @property {string} [backdrop] `stage` (default), any theme preset, or CSS
 * @property {string} [art] artwork over the backdrop, as on a card
 * @property {StageWords} [words] captions and title cards drawn on the stage
 * @property {string} [live] markup for a scene that moves under the window (the
 *   glass backdrop on a video), seeked per frame through `window.__glass`
 * @property {number} [width] stage width in CSS px (default 1920)
 * @property {number} [height] (default 1080)
 * @property {number} [perspective] px; smaller is more dramatic (default 1800)
 * @property {number} [fit] how much of the stage the flat image may fill (default 0.74)
 * @property {boolean} [glow] accent light behind the window (default on)
 * @property {boolean} [reflect] a faint reflection below the window
 * @property {boolean} [grid] a faint grid on the ground
 * @property {number} [radius] corner radius for `frame: "window"` (default 12)
 * @property {string} [src] image source; set later through `window.__stage` if absent
 */

/**
 * @typedef {object} StageWords
 * @property {string} [fonts] a stylesheet URL for the faces
 * @property {string} [titleFont] @property {string} [titleStyle] @property {string} [textFont]
 * @property {string} [accent] @property {string} [logo] a data: URL
 * @property {"bottom"|"top"} [at] where a caption sits
 */

/** How much the flat image is scaled to sit in the stage at `fit`. */
export function fitScale(o) {
  const w = o.width ?? STAGE_DEFAULTS.width;
  const h = o.height ?? STAGE_DEFAULTS.height;
  const fit = o.fit ?? STAGE_DEFAULTS.fit;
  return Math.min((w * fit) / o.imgWidth, (h * fit) / o.imgHeight);
}

/**
 * One self-contained page holding the stage. `window.__stage.set(src,
 * transform)` swaps the image and angle in place and resolves once the image is
 * decoded, which is how a video re-stages frame after frame without reloading.
 * @param {StageOptions} o
 */
export function stageDocument(o) {
  const theme = o.theme ?? "dark";
  const pal = palette(theme);
  const w = o.width ?? STAGE_DEFAULTS.width;
  const h = o.height ?? STAGE_DEFAULTS.height;
  const bd = o.backdrop ?? STAGE_DEFAULTS.backdrop;
  const ground = bd === "stage" ? STAGE_GROUND[theme] : backdrop(bd, theme);
  const k = fitScale(o);
  const radius = o.radius ?? 12;
  const dark = theme === "dark";
  const windowFrame =
    (o.frame ?? "window") === "window"
      ? `border:1px solid ${dark ? "rgba(255,255,255,.14)" : "rgba(0,0,0,.12)"};`
      : "";
  // A box-shadow on the window, not a drop-shadow filter on a wrapper: the
  // filter re-blurs the whole projected window on every frame, which was most
  // of a video's staging time. The box-shadow tilts with the window instead of
  // falling straight down, and the rounded corners keep it to the window's shape.
  const shadow = dark
    ? "0 50px 90px -20px rgba(0,0,0,.7), 0 14px 28px rgba(0,0,0,.45)"
    : "0 50px 90px -20px rgba(20,30,50,.3), 0 12px 24px rgba(20,30,50,.14)";
  const glow =
    o.glow === false
      ? ""
      : `<div id="glow" style="background:radial-gradient(closest-side, ${pal.accent}${dark ? "55" : "33"}, transparent)"></div>`;
  const grid = o.grid
    ? `<div id="grid" style="background-image:linear-gradient(${dark ? "rgba(255,255,255,.05)" : "rgba(0,0,0,.05)"} 1px, transparent 1px),linear-gradient(90deg, ${dark ? "rgba(255,255,255,.05)" : "rgba(0,0,0,.05)"} 1px, transparent 1px)"></div>`
    : "";
  const reflect = o.reflect
    ? `-webkit-box-reflect:below 10px linear-gradient(transparent 62%, rgba(255,255,255,${dark ? ".16" : ".28"}));`
    : "";

  const wd = o.words;
  const titleFont = wd?.titleFont ?? 'Georgia, "Times New Roman", serif';
  const titleStyle = wd?.titleStyle ?? "italic 600";
  const textFont = wd?.textFont ?? '-apple-system, "Segoe UI", system-ui, sans-serif';
  const ink = dark ? "#eaecef" : "#0e1a33";
  const muted = dark ? "#a9afb7" : "#4b5872";
  const halo = dark ? "0 2px 28px rgba(0,0,0,.75), 0 1px 3px rgba(0,0,0,.6)" : "0 2px 24px rgba(255,255,255,.8)";
  const capPos = wd?.at === "top" ? "top:7%" : "bottom:8%";
  // Words sit on a panel of their own, so they read over the window and the
  // art behind them alike.
  const panel = dark
    ? "background:rgba(10,12,16,.72);border:1px solid rgba(255,255,255,.08);box-shadow:0 18px 50px rgba(0,0,0,.45)"
    : "background:rgba(255,255,255,.78);border:1px solid rgba(14,26,51,.08);box-shadow:0 18px 50px rgba(14,26,51,.18)";
  const pad = `${Math.round(h * 0.026)}px ${Math.round(h * 0.034)}px`;
  const words = wd
    ? `#cap{position:absolute;left:6.5%;${capPos};max-width:46%;opacity:0;will-change:opacity,transform;
  padding:${pad};border-radius:${Math.round(h * 0.014)}px;${panel};-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
#title .panel{padding:${Math.round(h * 0.045)}px ${Math.round(h * 0.07)}px;border-radius:${Math.round(h * 0.02)}px;${panel};-webkit-backdrop-filter:blur(16px);backdrop-filter:blur(16px);display:flex;flex-direction:column;align-items:center}
#cap .t{font:${titleStyle} ${Math.round(h * 0.056)}px/1.04 ${titleFont};color:${ink};letter-spacing:-.01em;text-shadow:${halo}}
#cap .s{margin-top:${Math.round(h * 0.014)}px;font:400 ${Math.round(h * 0.022)}px/1.45 ${textFont};color:${muted};text-shadow:${halo};max-width:36em}
#cap .bar{width:${Math.round(h * 0.04)}px;height:3px;border-radius:2px;background:${wd.accent ?? pal.accent};margin-bottom:${Math.round(h * 0.02)}px}
#title{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;opacity:0}
#title img{width:${Math.round(h * 0.1)}px;height:auto;margin-bottom:${Math.round(h * 0.02)}px;filter:drop-shadow(0 8px 30px rgba(0,0,0,.5))}
#title .t{font:${titleStyle} ${Math.round(h * 0.13)}px/1 ${titleFont};color:${ink};letter-spacing:-.015em;text-shadow:${halo}}
#title .s{margin-top:${Math.round(h * 0.024)}px;font:400 ${Math.round(h * 0.026)}px/1.4 ${textFont};color:${muted};text-shadow:${halo}}`
    : "";
  return `<!doctype html><html><head><meta charset="utf-8">${wd?.fonts ? `<link rel="stylesheet" href="${wd.fonts}">` : ""}<style>
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:transparent}
#canvas{position:relative;width:${w}px;height:${h}px;overflow:hidden;background:${ground}}
#art{position:absolute;inset:0;image-rendering:pixelated;background:${o.art ?? "none"}}
#grid{position:absolute;inset:-50%;background-size:56px 56px;
  transform:perspective(${o.perspective ?? STAGE_DEFAULTS.perspective}px) rotateX(62deg) translateY(18%);
  -webkit-mask-image:radial-gradient(closest-side, #000 20%, transparent 80%)}
#glow{position:absolute;left:50%;top:50%;width:${Math.round(w * 0.9)}px;height:${Math.round(h * 0.9)}px;
  transform:translate(-50%,-50%)}
#scene{position:absolute;inset:0;display:grid;place-items:center${wd ? `;transform:translate(2.5%,${wd.at === "top" ? "3%" : "-3%"})` : ""}}
#win{${windowFrame}border-radius:${radius}px;overflow:hidden;box-shadow:${shadow};backface-visibility:hidden;${reflect}
  transform:${tiltTransform(o.tilt, k, o.perspective)};will-change:transform}
#win img{display:block;width:${o.imgWidth}px;height:${o.imgHeight}px}
${words}
</style></head><body><div id="canvas">${o.live ?? ""}${o.art && !o.live ? '<div id="art"></div>' : ""}${grid}${glow}
<div id="scene"><div id="win"><img id="shot" alt="" ${o.src ? `src="${o.src}"` : ""}></div></div>${
    wd ? `<div id="cap"></div><div id="title"><div class="panel">${wd.logo ? `<img src="${wd.logo}" alt="">` : ""}<div class="t"></div><div class="s"></div></div></div>` : ""
  }</div>
<script>
const esc = (t) => String(t).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);
let capText = null, titleText = null;
window.__stage = {
  async set(src, transform, frame, view) {
    const img = document.getElementById("shot");
    if (frame !== undefined && window.__glass) window.__glass.seek(frame);
    if (view) {
      const cap = document.getElementById("cap"), title = document.getElementById("title");
      if (cap && view.cap) {
        if (view.cap.text !== capText) {
          capText = view.cap.text;
          const [t, sub] = capText.split("|");
          cap.innerHTML = '<div class="bar"></div><div class="t">' + esc(t.trim()) + "</div>" +
            (sub ? '<div class="s">' + esc(sub.trim()) + "</div>" : "");
        }
        cap.style.opacity = view.cap.alpha;
        cap.style.transform = "translateY(" + ((1 - view.cap.alpha) * 14).toFixed(2) + "px)";
      }
      if (title && view.title) {
        if (view.title.text !== titleText) {
          titleText = view.title.text;
          const [t, sub] = titleText.split("|");
          title.querySelector(".t").textContent = (t || "").trim();
          title.querySelector(".s").textContent = (sub || "").trim();
        }
        title.style.opacity = view.title.alpha;
        title.style.transform = "scale(" + (0.985 + 0.015 * view.title.alpha).toFixed(4) + ")";
      }
      document.getElementById("scene").style.opacity = view.win;
    }
    if (src === null) return;
    if (transform) document.getElementById("win").style.transform = transform;
    if (src && img.getAttribute("src") !== src) { img.src = src; await img.decode().catch(() => {}); }
  },
};
</script></body></html>`;
}
