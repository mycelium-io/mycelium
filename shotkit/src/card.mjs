// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The window chrome shared by the terminal and code cards.
 *
 * One self-contained HTML document: no webfonts, no scripts, no fetches, so the
 * renderer can `setContent` and shoot in the same tick. The element actually
 * captured is `#canvas`, not `#card` — a box-shadow paints outside its element's
 * bounding box and an element screenshot clips to that box, so the padding
 * around the card is what keeps the shadow in frame.
 */

import { MONO_STACK, UI_STACK, backdrop, palette } from "./theme.mjs";

/** Traffic lights, in macOS order. */
const LIGHTS = ["#ff5f57", "#febc2e", "#28c840"];

const escapeHtml = (s) =>
  String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/**
 * @typedef {object} CardOptions
 * @property {"dark"|"light"} [theme]
 * @property {string} [backdrop] preset name or literal CSS
 * @property {number} [padding] gutter between backdrop edge and card
 * @property {number} [radius]
 * @property {boolean} [shadow]
 * @property {"mac"|"plain"|"browser"|"none"} [window] title bar style
 * @property {string} [address] address-bar text, for `window: "browser"`
 * @property {string} [bodyPadding] CSS padding for the body (default "16px 18px")
 * @property {string} [bodyBackground] CSS background for the body
 * @property {string} [title]
 * @property {number} [fontSize]
 * @property {number} [lineHeight]
 * @property {string} [font] CSS font-family override
 * @property {number} [cols] floor the body width at N characters
 * @property {number} [maxWidth] px cap on the shrink-wrapped card
 */

/**
 * @param {string} bodyHtml inner HTML of the card body
 * @param {CardOptions} opts
 * @param {string} [extraCss]
 */
export function cardDocument(bodyHtml, opts = {}, extraCss = "") {
  const theme = opts.theme ?? "dark";
  const pal = palette(theme);
  const pad = opts.padding ?? 40;
  const radius = opts.radius ?? 12;
  const chrome = opts.window ?? "mac";
  const fontSize = opts.fontSize ?? 13.5;
  const lineHeight = opts.lineHeight ?? 1.55;
  const font = opts.font ?? MONO_STACK;
  const shadow =
    opts.shadow === false
      ? "none"
      : theme === "dark"
        ? "0 22px 50px -12px rgba(0,0,0,.72), 0 2px 8px rgba(0,0,0,.5)"
        : "0 22px 50px -14px rgba(17,20,24,.28), 0 2px 8px rgba(17,20,24,.10)";

  // A floor, not a fixed width: `--cols` sets what the command was given for
  // COLUMNS, and output can still exceed it (an unwrappable path, a table). A
  // fixed width would clip that off the right edge silently, so the card grows.
  const bodyWidth = opts.cols ? `min-width:${opts.cols}ch;` : "";
  const maxWidth = opts.maxWidth ? `max-width:${opts.maxWidth}px;` : "";

  const lights =
    chrome === "mac" || chrome === "browser"
      ? `<div class="lights">${LIGHTS.map((c) => `<i style="background:${c}"></i>`).join("")}</div>`
      : "";
  // The browser bar puts the address where a browser puts it — centered, in a
  // pill — instead of the centered title a window bar shows.
  const titleBar =
    chrome === "none"
      ? ""
      : chrome === "browser"
        ? `<div class="bar browser">${lights}<div class="address">${escapeHtml(opts.address ?? opts.title ?? "")}</div></div>`
        : `<div class="bar">${lights}<div class="title">${escapeHtml(opts.title ?? "")}</div></div>`;

  return `<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}
html,body{margin:0;padding:0;background:transparent}
body{-webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}
#canvas{
  display:inline-block;width:max-content;padding:${pad}px;
  background:${backdrop(opts.backdrop ?? "mycelium", theme)};
}
#card{
  width:max-content;${maxWidth}
  background:${pal.paper};
  border:1px solid ${pal.border2};
  border-radius:${radius}px;
  box-shadow:${shadow};
  overflow:hidden;
}
.bar{
  display:flex;align-items:center;gap:10px;position:relative;
  height:34px;padding:0 12px;
  background:${pal.surface};
  border-bottom:1px solid ${pal.border};
}
.lights{display:flex;gap:7px}
.lights i{width:11px;height:11px;border-radius:50%;display:block}
.title{
  position:absolute;left:0;right:0;text-align:center;pointer-events:none;
  font-family:${UI_STACK};font-size:11.5px;letter-spacing:.02em;
  color:${pal.muted};
}
.bar.browser{height:44px;gap:14px}
.address{
  flex:1;min-width:0;height:26px;line-height:26px;padding:0 14px;
  border-radius:13px;background:${pal.bg};border:1px solid ${pal.border};
  font-family:${UI_STACK};font-size:11.5px;color:${pal.muted};
  text-align:center;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
}
/* Balances the traffic lights so the address pill sits centered. */
.bar.browser::after{content:"";width:53px;flex:none}
.body{
  /* content-box so an explicit --cols width means N characters of text, not
     N characters minus the padding. */
  box-sizing:content-box;
  ${bodyWidth}
  font-family:${font};
  font-size:${fontSize}px;line-height:${lineHeight};
  font-variant-ligatures:none;font-feature-settings:"liga" 0,"calt" 0;
  color:${pal.text};
  padding:${opts.bodyPadding ?? "16px 18px"};
  ${opts.bodyBackground ? `background:${opts.bodyBackground};` : ""}
  white-space:pre;tab-size:8;
}
${extraCss}
</style></head><body><div id="canvas"><div id="card">${titleBar}<div class="body">${bodyHtml}</div></div></div></body></html>`;
}

/**
 * Wrap an already-captured screenshot in the same window chrome the terminal and
 * code cards use.
 *
 * Deliberately the same path: a browser frame is a window frame with an address
 * bar, and giving it its own renderer would mean a second backdrop, a second
 * shadow and a second set of traffic lights to keep in step. The image goes in
 * as a data URI at its own CSS size, so one image pixel lands on one device
 * pixel and the wrap costs no sharpness.
 *
 * @param {string} base64 PNG bytes of the page capture
 * @param {number} cssWidth the capture's width in CSS pixels (device px / scale)
 * @param {CardOptions} opts
 */
export function imageCardDocument(base64, cssWidth, opts = {}) {
  const body = `<img src="data:image/png;base64,${base64}" width="${cssWidth}">`;
  return cardDocument(body, {
    window: "browser",
    ...opts,
    bodyPadding: "0",
  }, `.body img{display:block;width:${cssWidth}px;height:auto}`);
}

export { escapeHtml };
