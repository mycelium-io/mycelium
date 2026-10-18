// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A theme's color tokens, read from `globals.css` itself, for tests that check
 * what the app draws in every theme. jsdom resolves neither the theme's
 * variables nor `color-mix`, so the tests do that math on the real values.
 *
 * A theme's tokens are the blocks whose selector names its class, over
 * Mycelium light's defaults in :root, in the order the stylesheet applies them.
 */

import { readFileSync } from "node:fs";
import path from "node:path";

/** `globals.css` as written. */
export const css = readFileSync(path.resolve(__dirname, "../app/globals.css"), "utf8");
// The palette is everything before the first `@theme` rule (not a mention of
// one in a comment).
const palette = css.slice(0, css.search(/^@theme inline \{/m));

const blocks = [...palette.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(([, selectors, body]) => ({
  // What precedes a block can be comments and at-rules (`@import …;`): the
  // selector list is what follows the last of them.
  selectors: selectors
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split(";")
    .at(-1)!
    .split(",")
    .map((s) => s.trim()),
  tokens: Object.fromEntries(
    [...body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map(([, name, value]) => [name, value]),
  ),
}));

/** Every hex token the theme with class ``className`` sets, by name without `--`. */
export function themeTokens(className: string): Record<string, string> {
  return Object.assign(
    {},
    ...blocks
      .filter((b) => b.selectors.includes(":root") || b.selectors.includes(`.${className}`))
      .map((b) => b.tokens),
  );
}

export const rgb = (hex: string): number[] => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

function luminance(c: number[]): number {
  const [r, g, b] = c.map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast between two colors, each a hex string or `[r, g, b]`. */
export function contrast(a: string | number[], b: string | number[]): number {
  const [x, y] = [a, b].map((c) => luminance(typeof c === "string" ? rgb(c) : c));
  const [hi, lo] = [x, y].sort((p, q) => q - p);
  return (hi + 0.05) / (lo + 0.05);
}
