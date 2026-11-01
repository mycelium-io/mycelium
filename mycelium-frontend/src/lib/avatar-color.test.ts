// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The avatar's initials have to be readable on its fill in every theme, for
// every color in the palette. jsdom can't resolve `color-mix` or the theme's
// variables, so this reads the real values from globals.css and does the mix
// and the WCAG contrast math itself: change a token or a percentage and this
// says whether the avatars still read.

import { describe, expect, it } from "vitest";
import { AVATAR_FILL, AVATAR_INK, avatarTint, initials, softAvatar } from "@/lib/avatar-color";
import { THEMES } from "@/lib/themes";
import { contrast, rgb, themeTokens } from "@/test/theme-tokens";

/** `color-mix(in srgb, a p%, b)`: each sRGB channel interpolated as stored. */
const mix = (a: number[], b: number[], p: number) => a.map((v, i) => v * (p / 100) + b[i] * (1 - p / 100));

describe("softAvatar", () => {
  it("mixes the initials with the theme's avatar ink, not a fixed white", () => {
    expect(softAvatar("var(--avatar-1)").color).toBe(
      `color-mix(in srgb, var(--avatar-1) ${AVATAR_INK}%, var(--avatar-ink))`,
    );
  });

  it.each(THEMES.map((t) => [t.label, t.className]))(
    "keeps the initials at 4.5:1 or better on every palette color in %s",
    (label, className) => {
      const t = themeTokens(className);
      const slots = Object.keys(t).filter((k) => /^avatar-\d+$/.test(k));
      expect(slots.length).toBeGreaterThan(0);
      for (const slot of slots) {
        const fill = mix(rgb(t[slot]), rgb(t.surface), AVATAR_FILL);
        // `--avatar-ink` is the theme's text unless the theme sets its own.
        const ink = mix(rgb(t[slot]), rgb(t["avatar-ink"] ?? t.text), AVATAR_INK);
        expect(contrast(ink, fill), `${slot} in ${label}`).toBeGreaterThanOrEqual(4.5);
      }
    },
  );
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
