// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The avatar's initials have to be readable on its fill in both themes, for
// every color in the palette. jsdom can't resolve `color-mix` or the theme's
// variables, so this reads the real values from globals.css and does the mix
// and the WCAG contrast math itself: change a token or a percentage and this
// says whether the avatars still read.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { AVATAR_FILL, AVATAR_INK, avatarTint, initials, softAvatar } from "@/lib/avatar-color";

const CSS = readFileSync(path.resolve(__dirname, "../app/globals.css"), "utf-8");

/** The custom properties set in the first block that opens with `selector {`. */
function tokens(selector: string): Record<string, string> {
  const start = CSS.indexOf(`${selector} {`);
  const body = CSS.slice(start, CSS.indexOf("\n}", start));
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)].map((m) => [m[1], m[2]]));
}

const rgb = (hex: string) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

/** `color-mix(in srgb, a p%, b)`: each sRGB channel interpolated as stored. */
const mix = (a: number[], b: number[], p: number) => a.map((v, i) => v * (p / 100) + b[i] * (1 - p / 100));

function luminance(c: number[]): number {
  const [r, g, b] = c.map((v) => {
    const s = v / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: number[], b: number[]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const light = tokens(":root");
const dark = { ...light, ...tokens(".dark") };

describe("softAvatar", () => {
  it("mixes the initials with the theme's text color, not a fixed white", () => {
    expect(softAvatar("var(--avatar-1)").color).toBe(`color-mix(in srgb, var(--avatar-1) ${AVATAR_INK}%, var(--text))`);
  });

  for (const [theme, t] of [["light", light], ["dark", dark]] as const) {
    it(`keeps the initials at 4.5:1 or better on every palette color in ${theme} mode`, () => {
      const slots = Object.keys(t).filter((k) => /^--avatar-\d+$/.test(k));
      expect(slots.length).toBeGreaterThan(0);
      for (const slot of slots) {
        const fill = mix(rgb(t[slot]), rgb(t["--surface"]), AVATAR_FILL);
        const ink = mix(rgb(t[slot]), rgb(t["--text"]), AVATAR_INK);
        expect(contrast(ink, fill), `${slot} in ${theme} mode`).toBeGreaterThanOrEqual(4.5);
      }
    });
  }
});

describe("avatarTint and initials", () => {
  it("picks a palette slot from the name, the same every time", () => {
    expect(avatarTint("builder")).toMatch(/^var\(--avatar-[1-6]\)$/);
    expect(avatarTint("Builder")).toBe(avatarTint("builder"));
  });

  it("takes two letters", () => {
    expect(initials("backend-lead")).toBe("BL");
    expect(initials("main")).toBe("MA");
  });
});
