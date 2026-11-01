// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The app's color themes. Each one is a block of tokens in `app/globals.css`,
 * under the class named here; everything the app draws reads those tokens, so a
 * theme is only ever a set of values, never code.
 *
 * `light` and `dark` keep their ids so a choice saved before there were other
 * themes still applies; they're labelled as Mycelium's own. `mode` says which
 * the browser should draw its own parts in (scrollbars, a select's list), and
 * which icon stands for the theme.
 */

import { CUSTOM_CLASS, CUSTOM_THEME } from "@/lib/custom-themes";

export type ThemeMode = "light" | "dark";

export interface Theme {
  id: string;
  label: string;
  mode: ThemeMode;
  /** The class on <html> that selects the theme's tokens. */
  className: string;
}

export const THEMES: readonly Theme[] = [
  { id: "light", label: "Mycelium light", mode: "light", className: "light" },
  { id: "dark", label: "Mycelium dark", mode: "dark", className: "dark" },
  { id: "catppuccin-latte", label: "Catppuccin Latte", mode: "light", className: "theme-catppuccin-latte" },
  { id: "catppuccin-mocha", label: "Catppuccin Mocha", mode: "dark", className: "theme-catppuccin-mocha" },
  { id: "dracula", label: "Dracula", mode: "dark", className: "theme-dracula" },
  { id: "github-light", label: "GitHub light", mode: "light", className: "theme-github-light" },
  { id: "github-dark", label: "GitHub dark", mode: "dark", className: "theme-github-dark" },
  { id: "gruvbox-light", label: "Gruvbox light", mode: "light", className: "theme-gruvbox-light" },
  { id: "gruvbox-dark", label: "Gruvbox dark", mode: "dark", className: "theme-gruvbox-dark" },
  { id: "high-contrast-light", label: "High contrast light", mode: "light", className: "theme-high-contrast-light" },
  { id: "high-contrast-dark", label: "High contrast dark", mode: "dark", className: "theme-high-contrast-dark" },
  { id: "nord", label: "Nord", mode: "dark", className: "theme-nord" },
  { id: "one-dark", label: "One Dark", mode: "dark", className: "theme-one-dark" },
  { id: "solarized-light", label: "Solarized light", mode: "light", className: "theme-solarized-light" },
  { id: "solarized-dark", label: "Solarized dark", mode: "dark", className: "theme-solarized-dark" },
  { id: "tokyo-night", label: "Tokyo Night", mode: "dark", className: "theme-tokyo-night" },
];

/** Follow the computer's light or dark setting, with Mycelium's two themes. */
export const SYSTEM = "system";

/** What next-themes is given: every theme id, and the class each one sets.
 *  The custom theme is one more id; which imported theme it shows, and its
 *  colors, are set beside it (`components/custom-theme.tsx`). */
export const THEME_IDS = [...THEMES.map((t) => t.id), CUSTOM_THEME];
export const THEME_CLASSES: Record<string, string> = {
  ...Object.fromEntries(THEMES.map((t) => [t.id, t.className])),
  [CUSTOM_THEME]: CUSTOM_CLASS,
};

export function themeById(id: string | undefined): Theme | undefined {
  return THEMES.find((t) => t.id === id);
}

/** Whether ``id`` (a theme, or what "system" resolved to) draws dark. The
 *  custom theme's mode is its own, so a caller showing it passes that. */
export function modeOf(id: string | undefined, customMode?: ThemeMode): ThemeMode {
  if (id === CUSTOM_THEME && customMode) return customMode;
  return themeById(id)?.mode ?? "dark";
}
