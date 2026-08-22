// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Named frames, so "does this look right on a phone" is one word rather than
 * three numbers. Sizes are CSS pixels at each device's real pixel ratio, which
 * is what the app's media queries respond to.
 */

/** @typedef {{width:number, height:number, scale:number, label:string}} Viewport */

/** @type {Record<string, Viewport>} */
export const VIEWPORTS = {
  phone: { width: 390, height: 844, scale: 3, label: "iPhone 15 · 390×844" },
  "phone-sm": { width: 360, height: 780, scale: 3, label: "Small Android · 360×780" },
  tablet: { width: 834, height: 1112, scale: 2, label: "iPad Air · 834×1112" },
  laptop: { width: 1280, height: 800, scale: 2, label: "Laptop · 1280×800" },
  desktop: { width: 1440, height: 900, scale: 2, label: "Desktop · 1440×900" },
  wide: { width: 1920, height: 1080, scale: 2, label: "Wide · 1920×1080" },
};

/** The ladder `--responsive` walks: one frame either side of every breakpoint. */
export const RESPONSIVE_SET = ["phone", "tablet", "laptop", "wide"];

/**
 * Resolve `--viewport`: a preset name, or `WIDTHxHEIGHT[@SCALE]`.
 * @param {string} name
 * @returns {Viewport}
 */
export function resolveViewport(name) {
  const preset = VIEWPORTS[name];
  if (preset) return preset;
  const m = /^(\d+)x(\d+)(?:@([\d.]+))?$/.exec(String(name).trim());
  if (!m) {
    throw new Error(`unknown viewport "${name}". Presets: ${Object.keys(VIEWPORTS).join(", ")}, or 1280x800@2`);
  }
  const width = Number(m[1]);
  const height = Number(m[2]);
  const scale = m[3] ? Number(m[3]) : 2;
  return { width, height, scale, label: `${width}×${height}` };
}

/**
 * Expand `--viewports a,b,c` / `--responsive` into the list to shoot.
 * @param {{viewport?:string, viewports?:string, responsive?:boolean}} spec
 * @returns {{name:string, viewport:Viewport}[]}
 */
export function viewportList(spec) {
  let names;
  if (spec.viewports) names = String(spec.viewports).split(",").map((s) => s.trim()).filter(Boolean);
  else if (spec.responsive) names = RESPONSIVE_SET;
  else if (spec.viewport) names = [spec.viewport];
  else return [];
  return names.map((name) => ({ name, viewport: resolveViewport(name) }));
}
