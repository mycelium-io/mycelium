// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { THEMES } from "@/lib/themes";
import { contrast, themeTokens } from "@/test/theme-tokens";

/**
 * Every theme's text is readable on every surface it sits on: WCAG AA, 4.5:1.
 *
 * Read from `globals.css` itself, so a theme added there, or a token changed,
 * is held to the same floor with nothing to keep in step.
 */

const AA = 4.5;
const SURFACES = ["bg", "surface", "paper", "elevated", "muted-bg"];
/** Foregrounds that carry words, and the surfaces each must read on. */
const PAIRS: [string, string[]][] = [
  ["text", SURFACES],
  ["prose", SURFACES],
  ["muted-foreground", SURFACES],
  ["faint", SURFACES],
  // Links, mentions and the accent's own labels.
  ["accent", ["bg", "surface", "paper", "elevated"]],
  // State in words: an error line, "merged", "waiting".
  ["red", ["bg", "surface", "elevated"]],
  ["green", ["bg", "surface", "elevated"]],
  ["yellow", ["bg", "surface", "elevated"]],
  // The Stream names each task's thread in its lane's color.
  ...[1, 2, 3, 4, 5, 6, 7, 8].map((n): [string, string[]] => [`lane-${n}`, ["bg"]]),
];

describe.each(THEMES.map((t) => [t.label, t] as const))("%s", (_label, theme) => {
  const tokens = themeTokens(theme.className);

  it("has every token the app reads", () => {
    const needed = [...new Set(PAIRS.flatMap(([fg, bgs]) => [fg, ...bgs])), "accent-fg"];
    expect(needed.filter((t) => !tokens[t])).toEqual([]);
  });

  it("keeps its text, accent and state colors at AA on its surfaces", () => {
    const failing = PAIRS.flatMap(([fg, bgs]) =>
      bgs
        .map((bg) => ({ fg, bg, ratio: contrast(tokens[fg], tokens[bg]) }))
        .filter(({ ratio }) => ratio < AA)
        .map(({ fg, bg, ratio }) => `${fg} ${tokens[fg]} on ${bg} ${tokens[bg]}: ${ratio.toFixed(2)}`),
    );
    expect(failing).toEqual([]);
  });

  it("keeps the accent's own label readable on it", () => {
    expect(contrast(tokens["accent-fg"], tokens.accent)).toBeGreaterThanOrEqual(AA);
  });

  it("keeps its text levels in order: primary, then secondary, then faint", () => {
    const on = (fg: string) => contrast(tokens[fg], tokens.bg);
    expect(on("text")).toBeGreaterThanOrEqual(on("muted-foreground"));
    expect(on("muted-foreground")).toBeGreaterThanOrEqual(on("faint"));
  });
});
