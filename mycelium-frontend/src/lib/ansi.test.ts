// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { channels, color256, MIN_CONTRAST, parseAnsi, readable } from "./ansi";

/** WCAG contrast between two colors, for checking what `readable` gives. */
function contrastOf(a: string, b: string): number {
  const lum = (c: string) => {
    const [r, g, bl] = channels(c)!.map((v) => {
      const x = v / 255;
      return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("a terminal color on the page", () => {
  const cream = "rgb(250, 245, 230)";
  const night = "rgb(20, 22, 26)";

  it("is made readable where a dark terminal's color would vanish", () => {
    for (const fg of ["#eeeeec", "#8ae234", "rgb(255, 255, 255)"]) {
      const shown = readable(fg, cream);
      expect(shown).not.toBe(fg);
      expect(contrastOf(shown, cream)).toBeGreaterThanOrEqual(MIN_CONTRAST);
    }
    // Dark text on a dark view, the other way round.
    expect(contrastOf(readable("#2e3436", night), night)).toBeGreaterThanOrEqual(MIN_CONTRAST);
  });

  it("is left alone when it can already be read, or isn't a color it can read", () => {
    expect(readable("#2e3436", cream)).toBe("#2e3436");
    expect(readable("#eeeeec", night)).toBe("#eeeeec");
    expect(readable("var(--text)", cream)).toBe("var(--text)");
    expect(readable("#eeeeec", "var(--bg)")).toBe("#eeeeec");
  });
});

describe("a terminal snapshot's colors", () => {
  it("reads each line into runs of styled text", () => {
    const lines = parseAnsi("\x1b[1;32m● working\x1b[0m on it\r\n\x1b[38;5;196mred\x1b[39m plain\r\n");
    expect(lines).toHaveLength(2);
    expect(lines[0][0]).toMatchObject({ text: "● working", style: { bold: true, fg: "#4e9a06" } });
    expect(lines[0][1]).toMatchObject({ text: " on it", style: { bold: false, fg: null } });
    expect(lines[1][0]).toMatchObject({ text: "red", style: { fg: color256(196) } });
    expect(lines[1][1].style.fg).toBeNull();
  });

  it("reads truecolor and backgrounds", () => {
    const [[run]] = parseAnsi("\x1b[38;2;92;199;210;48;5;236mcyan\x1b[0m");
    expect(run.style.fg).toBe("rgb(92, 199, 210)");
    expect(run.style.bg).toBe(color256(236));
  });

  it("keeps a style across lines until it's reset", () => {
    const lines = parseAnsi("\x1b[2mone\ntwo\x1b[0m\nthree");
    expect(lines[1][0].style.dim).toBe(true);
    expect(lines[2][0].style.dim).toBe(false);
  });

  it("drops every escape that isn't a color, so a screen can't move or title anything", () => {
    const lines = parseAnsi("a\x1b[2J\x1b[10;5Hb\x1b]0;title\x07c\x1b[?25ld\x07e");
    expect(lines.map((l) => l.map((r) => r.text).join(""))).toEqual(["abcde"]);
  });

  it("keeps blank lines inside a screen, not the newline at its end", () => {
    expect(parseAnsi("top\n\nbottom\n")).toHaveLength(3);
  });

  it("maps the 256-color cube and grays", () => {
    expect(color256(16)).toBe("rgb(0, 0, 0)");
    expect(color256(231)).toBe("rgb(255, 255, 255)");
    expect(color256(232)).toBe("rgb(8, 8, 8)");
  });
});
