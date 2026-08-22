// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The look. Surfaces, text and the 16 ANSI slots, in both themes.
 *
 * Values track `mycelium-frontend/src/app/globals.css` so a terminal card sits
 * next to an app screenshot without clashing: same canvas, same hairlines, same
 * accent. The ANSI slots reuse the frontend's semantic and categorical hues
 * rather than the stock VGA palette, which is why `mycelium memory ls` shades
 * the same teal in a screenshot as it does in the product.
 */

/** @typedef {"dark"|"light"} ThemeName */

/** @type {Record<ThemeName, Record<string, string>>} */
export const THEMES = {
  dark: {
    bg: "#0c0e11",
    surface: "#14171c",
    paper: "#191d22",
    elevated: "#21262d",
    text: "#e8ebee",
    muted: "#a7adb5",
    faint: "#565d65",
    border: "rgba(255, 255, 255, 0.08)",
    border2: "rgba(255, 255, 255, 0.16)",
    accent: "#5cc7d2",
    accentFg: "#06181b",
    accentSoft: "rgba(92, 199, 210, 0.13)",
    green: "#4fc296",
    yellow: "#d9a94e",
    red: "#e6746f",
    // 0-7 then bright 8-15.
    ansi: [
      "#21262d", "#e6746f", "#4fc296", "#d9a94e",
      "#656fe2", "#e265ae", "#5cc7d2", "#e8ebee",
      "#565d65", "#f0918c", "#6fd6ae", "#e6c274",
      "#8a92ea", "#ea8cc2", "#7fd9e2", "#ffffff",
    ],
  },
  light: {
    bg: "#ffffff",
    surface: "#f2f4f6",
    paper: "#ffffff",
    elevated: "#ffffff",
    text: "#14171b",
    muted: "#545c65",
    faint: "#9198a0",
    border: "rgba(17, 20, 24, 0.10)",
    border2: "rgba(17, 20, 24, 0.17)",
    accent: "#0c7d8f",
    accentFg: "#ffffff",
    accentSoft: "rgba(12, 125, 143, 0.10)",
    green: "#0d8a63",
    yellow: "#8a6410",
    red: "#bd3f3a",
    ansi: [
      "#14171b", "#bd3f3a", "#0d8a63", "#8a6410",
      "#212fca", "#ca2183", "#0c7d8f", "#545c65",
      "#9198a0", "#d4615b", "#12a87b", "#a87d1b",
      "#4450d8", "#d84a9f", "#1298ad", "#14171b",
    ],
  },
};

/**
 * Backdrops the card floats on. `none` leaves the canvas transparent, which is
 * what you want when the image is going into a page that has its own
 * background; everything else pads the card so the drop shadow has room.
 *
 * `mycelial` is the ground the docs site paints its hypha network on. Asking
 * for it also asks for the network itself, which is not a CSS value and so
 * arrives separately (see mycelial.mjs); this entry is what shows if that
 * render is unavailable, which is why it is the site's canvas color and not a
 * gradient of its own.
 */
export const BACKDROPS = {
  mycelium: {
    dark: "radial-gradient(120% 120% at 12% 0%, #17323a 0%, #101a20 45%, #0a0c0f 100%)",
    light: "radial-gradient(120% 120% at 12% 0%, #dff1f4 0%, #eef2f4 45%, #e4e8ec 100%)",
  },
  dusk: {
    dark: "linear-gradient(135deg, #2b2140 0%, #1b1930 55%, #101019 100%)",
    light: "linear-gradient(135deg, #efe7fb 0%, #e6e9f7 55%, #dfe2ee 100%)",
  },
  mycelial: { dark: "#0c0e11", light: "#f4ecda" },
  ink: { dark: "#08090b", light: "#eceef1" },
  paper: { dark: "#14171c", light: "#f2f4f6" },
  none: { dark: "transparent", light: "transparent" },
};

/**
 * Font stacks, not webfonts: the renderer must not touch the network, so each
 * stack lists the macOS face first and the face that ships on this repo's Linux
 * images second. Editing these is how you retarget the tool at a new host.
 */
export const MONO_STACK =
  'ui-monospace, "SF Mono", SFMono-Regular, Menlo, "JetBrains Mono", ' +
  '"IBM Plex Mono", "DejaVu Sans Mono", "Liberation Mono", Consolas, monospace';

export const UI_STACK =
  '-apple-system, BlinkMacSystemFont, "Inter", "IBM Plex Sans", ' +
  '"DejaVu Sans", "Liberation Sans", system-ui, sans-serif';

/** @param {ThemeName} name */
export function palette(name) {
  return THEMES[name] ?? THEMES.dark;
}

/**
 * Resolve `--backdrop`: a preset name, or any CSS the caller wants to drop in
 * verbatim (`"#111"`, `"linear-gradient(...)"`).
 * @param {string} value
 * @param {ThemeName} theme
 */
export function backdrop(value, theme) {
  const preset = BACKDROPS[value];
  if (preset) return preset[theme];
  return value;
}
