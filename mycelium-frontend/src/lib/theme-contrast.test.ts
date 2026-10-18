// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { CUSTOM_DARK_CLASS } from "@/lib/custom-themes";
import { CONTRAST_PAIRS, contrast, contrastProblems } from "@/lib/theme-contrast";
import { THEMES } from "@/lib/themes";
import { css, themeTokens } from "@/test/theme-tokens";

/**
 * Every theme's text is readable on every surface it sits on: WCAG AA, 4.5:1.
 *
 * Read from `globals.css` itself, so a theme added there, or a token changed,
 * is held to the same floor with nothing to keep in step. The pairs are the
 * app's own (`lib/theme-contrast.ts`), the ones an imported theme is checked on.
 */

describe.each(THEMES.map((t) => [t.label, t] as const))("%s", (_label, theme) => {
  const tokens = themeTokens(theme.className);

  it("has every token the app reads", () => {
    const needed = [...new Set(CONTRAST_PAIRS.flatMap(([fg, bgs]) => [fg, ...bgs])), "accent-fg"];
    expect(needed.filter((t) => !tokens[t])).toEqual([]);
  });

  it("keeps its text, accent and state colors at AA on its surfaces, and the accent's label on it", () => {
    const failing = contrastProblems(tokens).map(
      ({ fg, bg, ratio }) => `${fg} ${tokens[fg]} on ${bg} ${tokens[bg]}: ${ratio.toFixed(2)}`,
    );
    expect(failing).toEqual([]);
  });

  it("keeps its text levels in order: primary, then secondary, then faint", () => {
    const on = (fg: string) => contrast(tokens[fg], tokens.bg);
    expect(on("text")).toBeGreaterThanOrEqual(on("muted-foreground"));
    expect(on("muted-foreground")).toBeGreaterThanOrEqual(on("faint"));
  });
});

describe("dark themes in globals.css", () => {
  // A dark theme is named in `lib/themes.ts` and twice in the stylesheet: the
  // `dark` variant, so a `dark:` class applies under it, and the block that
  // sets `color-scheme: dark`, so the browser's own pieces (a select's option
  // list, scrollbars) are drawn dark. Each list is read here and compared.
  const classesIn = (text: string) => new Set([...text.matchAll(/\.([\w-]+)/g)].map((m) => m[1]));
  const variant = classesIn(css.match(/@custom-variant dark \(([\s\S]*?)\)\);/)![1]);
  const scheme = classesIn(
    [...css.matchAll(/([^{}]+)\{[^{}]*color-scheme:\s*dark[^{}]*\}/g)]
      .map((m) => m[1].replace(/\/\*[\s\S]*?\*\//g, ""))
      .join(","),
  );
  // A dark custom theme draws through the same lists, under its own class.
  const darkClasses = new Set([
    ...THEMES.filter((t) => t.mode === "dark").map((t) => t.className),
    CUSTOM_DARK_CLASS,
  ]);

  it("names exactly the dark themes in the dark variant", () => {
    expect(variant).toEqual(darkClasses);
  });

  it("draws exactly the dark themes with the browser's dark color scheme", () => {
    expect(scheme).toEqual(darkClasses);
  });
});
