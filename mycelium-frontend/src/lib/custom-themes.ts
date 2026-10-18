// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A theme someone brings themselves, as JSON:
 *
 *     { "name": "Midnight", "mode": "dark",
 *       "colors": { "bg": "#0b1020", "surface": "#0e1428", … } }
 *
 * The colors are the app's own tokens (the ones every built-in theme sets in
 * `globals.css`), by name, as hex. Nothing else is accepted: no CSS, no other
 * property, no color the app doesn't read, so a theme can recolor the app and
 * do nothing more. Lines and the accent's tint are worked out from the text and
 * the accent when a theme leaves them out; the graph, Stream-lane and avatar
 * palettes follow `mode`, as they do for the built-in themes.
 */

import type { ThemeMode } from "@/lib/themes";
import { contrastProblems, type ContrastProblem } from "@/lib/theme-contrast";

/** next-themes' id for "the custom theme picked in settings". */
export const CUSTOM_THEME = "custom";
/** The class next-themes puts on <html> for it. */
export const CUSTOM_CLASS = "theme-custom";
/** Added beside it when the custom theme is dark, so the browser's own pieces
 *  and the dark palettes follow (it's in both of globals.css's dark lists). */
export const CUSTOM_DARK_CLASS = "theme-custom-dark";

/** The colors a theme has to give: every surface, every text level, the
 *  accent and the label on it, and the three state colors. */
export const REQUIRED_COLORS = [
  "bg",
  "surface",
  "paper",
  "elevated",
  "muted-bg",
  "text",
  "muted-foreground",
  "faint",
  "accent",
  "accent-fg",
  "green",
  "yellow",
  "red",
] as const;

/** The colors a theme may give; each has a default worked out from the rest. */
export const OPTIONAL_COLORS = ["prose", "border", "border2", "hairline", "accent-soft", "avatar-ink"] as const;

/** Colors that sit under or around text may be see-through; text and the
 *  surfaces it's read on have to be solid, or contrast can't be known. */
export const MAY_BE_TRANSLUCENT = new Set(["border", "border2", "hairline", "accent-soft"]);

const ALL_COLORS = new Set<string>([...REQUIRED_COLORS, ...OPTIONAL_COLORS]);
const SOLID = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i;
const ANY_HEX = /^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
export const NAME_MAX = 40;

export interface CustomTheme {
  /** Stable, from the name: `custom-midnight`. */
  id: string;
  name: string;
  mode: ThemeMode;
  /** Token name (no `--`) to lowercase hex. */
  colors: Record<string, string>;
}

export type ParsedTheme = { ok: true; theme: CustomTheme } | { ok: false; errors: string[] };

function slug(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function normalize(hex: string): string {
  const h = hex.toLowerCase();
  return h.length === 4 ? `#${[...h.slice(1)].map((c) => c + c).join("")}` : h;
}

/**
 * A custom theme from JSON text or an already-parsed value, or every reason it
 * can't be one. Strict on purpose: an unknown color is named rather than
 * dropped, since it's usually a typo for one the app does read.
 */
export function parseCustomTheme(raw: unknown): ParsedTheme {
  let value = raw;
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw);
    } catch {
      return { ok: false, errors: ["That isn't JSON. A theme is an object with a name, a mode and its colors."] };
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { ok: false, errors: ["A theme is an object with a name, a mode and its colors."] };
  }
  const { name, mode, colors } = value as Record<string, unknown>;
  const errors: string[] = [];
  const title = typeof name === "string" ? name.trim() : "";
  if (!title) errors.push('It needs a "name".');
  else if (title.length > NAME_MAX) errors.push(`Its name is longer than ${NAME_MAX} characters.`);
  else if (!slug(title)) errors.push("Its name needs at least one letter or digit.");
  if (mode !== "light" && mode !== "dark") errors.push('Its "mode" has to be "light" or "dark".');
  if (!colors || typeof colors !== "object" || Array.isArray(colors)) {
    errors.push('It needs "colors": an object of the app\'s color names to hex colors.');
    return { ok: false, errors };
  }
  const out: Record<string, string> = {};
  for (const [key, color] of Object.entries(colors as Record<string, unknown>)) {
    if (!ALL_COLORS.has(key)) {
      errors.push(`"${key}" isn't a color the app reads.`);
      continue;
    }
    const pattern = MAY_BE_TRANSLUCENT.has(key) ? ANY_HEX : SOLID;
    if (typeof color !== "string" || !pattern.test(color)) {
      const form = MAY_BE_TRANSLUCENT.has(key) ? "#rgb, #rrggbb or #rrggbbaa" : "#rgb or #rrggbb";
      errors.push(`"${key}" has to be a hex color (${form}).`);
      continue;
    }
    out[key] = normalize(color);
  }
  const missing = REQUIRED_COLORS.filter((c) => !(c in (colors as object)));
  if (missing.length) errors.push(`It's missing ${missing.map((m) => `"${m}"`).join(", ")}.`);
  if (errors.length) return { ok: false, errors };
  return {
    ok: true,
    theme: { id: `custom-${slug(title)}`, name: title, mode: mode as ThemeMode, colors: out },
  };
}

/** The CSS variables a custom theme sets on <html>, its own colors and the
 *  defaults for the ones it left out. Every value is one of its hex colors or
 *  a `color-mix` this code writes, never text from the theme. */
export function themeVars(theme: CustomTheme): Record<string, string> {
  const c = theme.colors;
  const vars: Record<string, string> = {
    "--prose": c.text,
    "--border": `color-mix(in srgb, ${c.text} 10%, transparent)`,
    "--border2": `color-mix(in srgb, ${c.text} 18%, transparent)`,
    "--hairline": `color-mix(in srgb, ${c.text} 4%, transparent)`,
    "--accent-soft": `color-mix(in srgb, ${c.accent} 13%, transparent)`,
    "--avatar-ink": c.text,
  };
  for (const [key, value] of Object.entries(c)) vars[`--${key}`] = value;
  return vars;
}

/** Where a custom theme's words fall under AA, as the built-in themes are held to. */
export function customThemeProblems(theme: CustomTheme): ContrastProblem[] {
  return contrastProblems({ prose: theme.colors.text, ...theme.colors });
}

/** A theme's JSON, as someone would save it to share or edit. */
export function themeJson(theme: Pick<CustomTheme, "name" | "mode" | "colors">): string {
  return JSON.stringify({ name: theme.name, mode: theme.mode, colors: theme.colors }, null, 2);
}

/** The theme showing now, as a custom theme's JSON to start from: every color
 *  it can set, read off the page. ``read`` returns a CSS variable's value. */
export function templateFrom(read: (variable: string) => string, name: string, mode: ThemeMode): string {
  const colors: Record<string, string> = {};
  for (const key of [...REQUIRED_COLORS, ...OPTIONAL_COLORS]) {
    const value = read(`--${key}`).trim();
    if (ANY_HEX.test(value)) colors[key] = normalize(value);
  }
  return themeJson({ name, mode, colors });
}

/** Stored themes, each re-checked, so a hand edit can't bring in a bad one;
 *  the later of two with the same name wins. */
export function sanitizeCustomThemes(raw: unknown): CustomTheme[] {
  if (!Array.isArray(raw)) return [];
  const byId = new Map<string, CustomTheme>();
  for (const item of raw) {
    const parsed = parseCustomTheme(item);
    if (parsed.ok) byId.set(parsed.theme.id, parsed.theme);
  }
  return [...byId.values()];
}
