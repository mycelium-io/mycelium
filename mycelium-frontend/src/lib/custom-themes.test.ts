// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  customThemeProblems,
  parseCustomTheme,
  sanitizeCustomThemes,
  templateFrom,
  themeVars,
  type CustomTheme,
} from "@/lib/custom-themes";
import { themeTokens } from "@/test/theme-tokens";

/** Mycelium dark's own colors, as a theme someone could bring. */
const COLORS = {
  bg: "#0c0e11",
  surface: "#14171c",
  paper: "#191d22",
  elevated: "#21262d",
  "muted-bg": "#21262d",
  text: "#e8ebee",
  "muted-foreground": "#a7adb5",
  faint: "#888f97",
  accent: "#5cc7d2",
  "accent-fg": "#06181b",
  green: "#4fc296",
  yellow: "#d9a94e",
  red: "#e6746f",
};
const VALID = { name: "Midnight Blue", mode: "dark", colors: COLORS };

function themeOf(raw: unknown): CustomTheme {
  const parsed = parseCustomTheme(raw);
  if (!parsed.ok) throw new Error(parsed.errors.join(" "));
  return parsed.theme;
}

describe("parseCustomTheme", () => {
  it("takes a theme as JSON text or as an object, with an id from its name", () => {
    expect(themeOf(JSON.stringify(VALID))).toEqual(themeOf(VALID));
    expect(themeOf(VALID)).toMatchObject({ id: "custom-midnight-blue", name: "Midnight Blue", mode: "dark" });
  });

  it("writes colors as six-digit lowercase hex", () => {
    const theme = themeOf({ ...VALID, colors: { ...COLORS, bg: "#ABC", accent: "#5CC7D2" } });
    expect([theme.colors.bg, theme.colors.accent]).toEqual(["#aabbcc", "#5cc7d2"]);
  });

  it("says why it can't take one, every reason at once", () => {
    const missing = Object.fromEntries(Object.entries(COLORS).filter(([key]) => key !== "bg" && key !== "faint"));
    const parsed = parseCustomTheme({ mode: "dusk", colors: { ...missing, backround: "#000000" } });
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.errors).toEqual([
      'It needs a "name".',
      'Its "mode" has to be "light" or "dark".',
      '"backround" isn\'t a color the app reads.',
      'It\'s missing "bg", "faint".',
    ]);
  });

  it("refuses anything but a hex color, so a theme can't carry CSS", () => {
    for (const value of ["red", "rgb(0, 0, 0)", "#000; background: url(x)", "var(--text)", 12]) {
      const parsed = parseCustomTheme({ ...VALID, colors: { ...COLORS, accent: value } });
      expect(parsed.ok, String(value)).toBe(false);
    }
  });

  it("lets lines and tints be see-through, but not text or the surfaces it sits on", () => {
    expect(parseCustomTheme({ ...VALID, colors: { ...COLORS, border: "#ffffff22" } }).ok).toBe(true);
    expect(parseCustomTheme({ ...VALID, colors: { ...COLORS, text: "#ffffff22" } }).ok).toBe(false);
    expect(parseCustomTheme({ ...VALID, colors: { ...COLORS, surface: "#00000080" } }).ok).toBe(false);
  });

  it("isn't JSON, or isn't an object", () => {
    expect(parseCustomTheme("{ not json")).toEqual({
      ok: false,
      errors: ["That isn't JSON. A theme is an object with a name, a mode and its colors."],
    });
    expect(parseCustomTheme([VALID]).ok).toBe(false);
  });
});

describe("themeVars", () => {
  it("sets the theme's colors and works out the ones it left out", () => {
    const vars = themeVars(themeOf(VALID));
    expect(vars["--bg"]).toBe("#0c0e11");
    expect(vars["--prose"]).toBe("#e8ebee");
    expect(vars["--avatar-ink"]).toBe("#e8ebee");
    expect(vars["--border"]).toBe("color-mix(in srgb, #e8ebee 10%, transparent)");
    expect(vars["--accent-soft"]).toBe("color-mix(in srgb, #5cc7d2 13%, transparent)");
  });

  it("uses what the theme gave over the worked-out default", () => {
    const vars = themeVars(themeOf({ ...VALID, colors: { ...COLORS, prose: "#c4cad1", border: "#ffffff14" } }));
    expect([vars["--prose"], vars["--border"]]).toEqual(["#c4cad1", "#ffffff14"]);
  });
});

describe("customThemeProblems", () => {
  it("passes a theme that reads at AA", () => {
    expect(customThemeProblems(themeOf(VALID))).toEqual([]);
  });

  it("names the words that would be hard to read", () => {
    const dim = themeOf({ ...VALID, colors: { ...COLORS, faint: "#3a3f45" } });
    expect(customThemeProblems(dim).map((p) => [p.fg, p.bg])).toEqual([
      ["faint", "bg"],
      ["faint", "surface"],
      ["faint", "paper"],
      ["faint", "elevated"],
      ["faint", "muted-bg"],
    ]);
  });
});

describe("templateFrom", () => {
  it("gives the theme showing now as JSON that imports cleanly", () => {
    // Read Mycelium dark's own tokens, as the page would show them.
    const tokens = themeTokens("dark");
    const json = templateFrom((v) => tokens[v.slice(2)] ?? "", "Mycelium dark (copy)", "dark");
    const theme = themeOf(json);
    expect(theme.name).toBe("Mycelium dark (copy)");
    expect(theme.colors.bg).toBe(tokens.bg);
    expect(customThemeProblems(theme)).toEqual([]);
  });
});

describe("sanitizeCustomThemes", () => {
  it("keeps the valid ones, the later of two with one name", () => {
    const again = { ...VALID, colors: { ...COLORS, accent: "#7aa2f7" } };
    const kept = sanitizeCustomThemes([VALID, { name: "Broken", mode: "dark", colors: {} }, again, "nope"]);
    expect(kept.map((t) => [t.id, t.colors.accent])).toEqual([["custom-midnight-blue", "#7aa2f7"]]);
    expect(sanitizeCustomThemes({ not: "a list" })).toEqual([]);
  });
});
