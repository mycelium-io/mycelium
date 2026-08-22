// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The contact sheet: every breakpoint of one screen, in one image.
 *
 * Written for the reader rather than the archive. Checking a responsive layout
 * means comparing four captures, and four files is four separate looks with the
 * previous one already out of view — so the frames are composed side by side at
 * their true relative widths, which is also what makes a phone beside a
 * 1920 monitor say something. The captures go in as data URIs, so composing
 * needs no image library and no second trip to disk.
 */

import { UI_STACK, backdrop, palette } from "./theme.mjs";

/** Widest sheet before everything is scaled down to fit. */
const MAX_SHEET_WIDTH = 2400;

/**
 * @param {{label:string, base64:string, width:number, height:number, scale:number}[]} frames
 * @param {{theme?:"dark"|"light", backdrop?:string, art?:string, title?:string, gap?:number, padding?:number}} opts
 */
export function sheetDocument(frames, opts = {}) {
  const theme = opts.theme ?? "dark";
  const pal = palette(theme);
  const gap = opts.gap ?? 32;
  const pad = opts.padding ?? 44;

  // Lay out in CSS pixels: a 390-wide phone must read as narrower than a
  // 1920-wide desktop, which it would not if each were normalized to fit.
  const cssWidths = frames.map((f) => f.width / (f.scale || 1));
  const total = cssWidths.reduce((a, b) => a + b, 0) + gap * (frames.length - 1);
  const k = Math.min(1, (MAX_SHEET_WIDTH - pad * 2) / total);

  const cards = frames
    .map((f, i) => {
      const w = Math.round(cssWidths[i] * k);
      return `<figure style="width:${w}px">
      <img src="data:image/png;base64,${f.base64}" width="${w}">
      <figcaption>${escapeHtml(f.label)}</figcaption>
    </figure>`;
    })
    .join("");

  const heading = opts.title
    ? `<h1>${escapeHtml(opts.title)}</h1>`
    : "";

  return `<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:transparent}
#canvas{
  position:relative;
  display:inline-block;width:max-content;padding:${pad}px;
  background:${backdrop(opts.backdrop ?? "mycelium", theme)};
  font-family:${UI_STACK};
}
/* The backdrop artwork, if there is any; see card.mjs for why it is a layer. */
#art{position:absolute;inset:0;image-rendering:pixelated;background:${opts.art ?? "none"}}
h1,.row{position:relative}
h1{
  margin:0 0 22px;font-size:15px;font-weight:600;letter-spacing:.01em;
  color:${pal.text};
}
.row{display:flex;align-items:flex-start;gap:${gap}px}
figure{margin:0;display:flex;flex-direction:column;gap:9px}
img{
  display:block;height:auto;border-radius:8px;
  border:1px solid ${pal.border2};
  box-shadow:0 18px 40px -14px rgba(0,0,0,${theme === "dark" ? ".7" : ".25"});
}
figcaption{
  font-size:11.5px;letter-spacing:.02em;color:${pal.muted};text-align:center;
}
</style></head><body><div id="canvas">${opts.art ? '<div id="art"></div>' : ""}${heading}<div class="row">${cards}</div></div></body></html>`;
}

const escapeHtml = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
